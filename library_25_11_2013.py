'''
--------------------------------------------------------------------------
                                Library
--------------------------------------------------------------------------                                
Created on May 13, 2013

Authors: Mostapha Harb - Daniele De Vecchi
         SENSUM Project
         University of Pavia - Remote Sensing Laboratory / EUCENTRE Foundation
         
In case of bugs or questions please contact: 
daniele.devecchi03@universitadipavia.it
mostapha.harb@eucentre.it
--------------------------------------------------------------------------
'''

import os, sys
import string
import osgeo.gdal,gdal
from osgeo.gdalconst import *
from gdalconst import *
import cv2
from cv2 import cv
import scipy as sp
import numpy as np
from numpy import unravel_index
import osgeo.osr
import osgeo.ogr
from collections import defaultdict
import random
#import grass.script.setup as gsetup
#import grass.script as grass
import skimage
from skimage.segmentation import felzenszwalb, slic, quickshift
from skimage.feature import greycomatrix
from skimage.feature import greycoprops
import multiprocessing
from multiprocessing import Pool
import scipy.stats
import otbApplication

if os.name == 'posix':
    separator = '/'
else:
    separator = '\\'

def shp_conversion(path,name_input,name_output,epsg):
    
    '''
    ###################################################################################################################
    Conversion from KML to SHP file using EPSG value as projection - Used to convert the drawn polygon around the city in GE to a SHP
    
     Input:
     - path: contains the folder path of the original file; the output file is going to be created into the same folder
     - name_input: name of the kml input file
     - name_output: name of shp output file
     - epsg: epsg projection code
     
     Output:
     SHP file is saved into the same folder of the original KML file
    ###################################################################################################################
    '''
    
    #conversion from kml to shapefile
    os.system("ogr2ogr -f 'ESRI Shapefile' " + path + name_output + ' ' + path + name_input)
    # set the working directory
    os.chdir(path)
    # get the shapefile driver
    driver = osgeo.ogr.GetDriverByName('ESRI Shapefile')
    # create the input SpatialReference, 4326 is the default one
    inSpatialRef = osgeo.osr.SpatialReference()
    inSpatialRef.ImportFromEPSG(4326)
    # create the output SpatialReference
    outSpatialRef = osgeo.osr.SpatialReference()
    outSpatialRef.ImportFromEPSG(epsg)
    # create the CoordinateTransformation
    coordTrans = osgeo.osr.CoordinateTransformation(inSpatialRef, outSpatialRef)
    # open the input data source and get the layer
    inDS = driver.Open(name_output, 0)
    if inDS is None:
        print 'Could not open file'
        sys.exit(1)
    inLayer = inDS.GetLayer()
    # create a new data source and layer
    if os.path.exists(name_output):
        driver.DeleteDataSource(name_output)
    outDS = driver.CreateDataSource(name_output)
    if outDS is None:
        print 'Could not create file'
        sys.exit(1)
    outLayer = outDS.CreateLayer('City', geom_type=osgeo.ogr.wkbPoint)
    # get the FieldDefn for the name field
    feature = inLayer.GetFeature(0)
    fieldDefn = feature.GetFieldDefnRef('name')
    # add the field to the output shapefile
    outLayer.CreateField(fieldDefn)
    # get the FeatureDefn for the output shapefile
    featureDefn = outLayer.GetLayerDefn()
    # loop through the input features
    inFeature = inLayer.GetNextFeature()
    while inFeature:
        # get the input geometry
        geom = inFeature.GetGeometryRef()
        # reproject the geometry
        geom.Transform(coordTrans)
        # create a new feature
        outFeature = osgeo.ogr.Feature(featureDefn)
        # set the geometry and attribute
        outFeature.SetGeometry(geom)
        outFeature.SetField('name', inFeature.GetField('name'))
        # add the feature to the shapefile
        outLayer.CreateFeature(outFeature)
        # destroy the features and get the next input feature
        outFeature.Destroy
        inFeature.Destroy
        inFeature = inLayer.GetNextFeature()
    # close the shapefiles
    inDS.Destroy()
    outDS.Destroy()
    # create the *.prj file
    outSpatialRef.MorphToESRI()
    file = open(name_output[:-4]+'.prj', 'w')
    file.write(outSpatialRef.ExportToWkt())
    file.close()
    print 'Conversion finished!'
    

def world2Pixel(geoMatrix, x, y):
    """
    Uses a gdal geomatrix (gdal.GetGeoTransform()) to calculate
    the pixel location of a geospatial coordinate 
    """
    ulX = geoMatrix[0]
    ulY = geoMatrix[3]
    xDist = geoMatrix[1]
    yDist = geoMatrix[5]
    rtnX = geoMatrix[2]
    rtnY = geoMatrix[4]
    pixel = int((x - ulX) / xDist)
    line = int((ulY - y) / xDist)
    return (pixel, line) 


def clip(path,name,shapefile):
    
    '''
    ###################################################################################################################
    Clip an image using a shapefile
    
    Input:
     - path: path to the images location in your pc
     - name: name of the input file
     - shapefile: path of the shapefile to be used
     
    Output:
    New file is saved into the same folder as "original_name_city.TIF"
    ###################################################################################################################  
    '''
    
    #os.system('gdalwarp -q -cutline ' + shapefile + ' -crop_to_cutline -of GTiff ' + path + name +' '+ path + name[:-4] + '_city.TIF')
    #new command working on fwtools, used just / for every file
    #print 'Clipped file: ' + name[:-4] + '_city.TIF'
    x_list = []
    y_list = []
    # get the shapefile driver
    driver = osgeo.ogr.GetDriverByName('ESRI Shapefile')
    
    # open the data source
    datasource = driver.Open(shapefile, 0)
    if datasource is None:
        print 'Could not open shapefile'
        sys.exit(1)

    layer = datasource.GetLayer() #get the shapefile layer
    inb = osgeo.gdal.Open(path+name, GA_ReadOnly)
    if inb is None:
        print 'Could not open'
        sys.exit(1)
        
    geoMatrix = inb.GetGeoTransform()
    driver = inb.GetDriver()
    cols = inb.RasterXSize
    rows = inb.RasterYSize    
    inband = inb.GetRasterBand(1)
    data = inband.ReadAsArray()
    # loop through the features in the layer
    feature = layer.GetNextFeature()
    while feature:
        # get the x,y coordinates for the point
        geom = feature.GetGeometryRef()
        #print geom
        ring = geom.GetGeometryRef(0)
        n_vertex = ring.GetPointCount()
        for i in range(0,n_vertex-1):
            lon,lat,z = ring.GetPoint(i)
            x_matrix,y_matrix = world2Pixel(inb.GetGeoTransform(),lon,lat)
            x_list.append(x_matrix)
            y_list.append(y_matrix)
        # destroy the feature and get a new one
        feature.Destroy()
        feature = layer.GetNextFeature()
    
    x_list.sort()
    x_min = x_list[0]
    y_list.sort()
    y_min = y_list[0]
    x_list.sort(None, None, True)
    x_max = x_list[0]
    y_list.sort(None, None, True)
    y_max = y_list[0]
    
    #compute the new starting coordinates
    lon_min = float(x_min*geoMatrix[1]+geoMatrix[0]) 
    lat_min = float(geoMatrix[3]-y_min*geoMatrix[5])
    #print lon_min
    #print lat_min
    
    geotransform = [lon_min,geoMatrix[1],0.0,lat_min,0.0,geoMatrix[5]]
    #print x_min,x_max
    #print y_min,y_max
    out=data[int(y_min):int(y_max),int(x_min):int(x_max)]
    cols_out = x_max-x_min
    rows_out = y_max-y_min
    output=driver.Create(path+name[:-4]+'_city.TIF',cols_out,rows_out,1)
    inprj=inb.GetProjection()
    #WriteOutputImage('/Users/daniele/Documents/Sensum/Izmir/Landsat5/LT51800331984164XXX04/LT51800331984164XXX04_B1.TIF','','','/Users/daniele/Documents/Sensum/Izmir/Landsat5/LT51800331984164XXX04/test.TIF',cols_out,rows_out,GDT_Float32,1,list_out)
    outband=output.GetRasterBand(1)
    outband.WriteArray(out,0,0) #write to output image
    output.SetGeoTransform(geotransform) #set the transformation
    output.SetProjection(inprj)
    # close the data source and text file
    datasource.Destroy()
    #print 'Clipped file: ' + name[:-4] + '_city.TIF'
    

def merge(path,output,name):
    
    '''
    ###################################################################################################################
    Merge different band-related files into a multi-band file
    
    Input:
     - path: folder path of the original files
     - output: name of the output file
     - name: input files to be merged
     
    Output:
    New file is created in the same folder
    ###################################################################################################################
    '''
    
    #function to extract single file names
    instring = name.split()
    num = len(instring)
    #os command to merge files into separate bands
    com = 'gdal_merge.py -separate -of GTiff -o ' + path + output
    for i in range(0,num):
        com = com + path + instring[i] + ' '
    os.system(com)
    print 'Output file: ' + output
    
    
def split(path,name,option):
    
    '''
    ###################################################################################################################
    Split the multi-band input image into different band-related files
    
    Input:
     - path: folder path of the image files
     - name: name of the input file to be split
     - option: specifies the band to extract, if equal to 0 all the bands are going to be extracted
    
    Output:
    Output file name contains the number of the extracted band - example: B1.TIF for band number 1
    ###################################################################################################################
    '''
    
    osgeo.gdal.AllRegister()
    #open the input file
    inputimg = osgeo.gdal.Open(path+name,GA_ReadOnly)
    if inputimg is None:
        print 'Could not open ' + name
        sys.exit(1)
    #extraction of columns, rows and bands from the input image    
    cols=inputimg.RasterXSize
    rows=inputimg.RasterYSize
    bands=inputimg.RasterCount
    
    if (option!=0):
        #extraction of just one band to a file
        inband=inputimg.GetRasterBand(option)
        driver=inputimg.GetDriver()
        output=driver.Create(path+'B'+str(option)+'.TIF',cols,rows,1)
        outband=output.GetRasterBand(1)
        data = inband.ReadAsArray()
        outband.WriteArray(data,0,0)
        print 'Output file: B' + str(option) + '.TIF'
    else:
        #extraction of all the bands to different files
        for i in range(1,bands+1):
            inband=inputimg.GetRasterBand(i)
    
            driver=inputimg.GetDriver()
            output=driver.Create(path+'B'+str(i)+'.TIF',cols,rows,1)
            outband=output.GetRasterBand(1)
    
            data = inband.ReadAsArray()
            outband.WriteArray(data,0,0)
            print 'Output file: B' + str(i) + '.TIF'
    inputimg=None   
    

def Extraction(img1,img2):
    
    '''
    ###################################################################################################################
    Feature Extraction using the SURF algorithm
    
    Input:
     - image1: path to the reference image - each following image is going to be matched with this reference
     - image2: path to the image to be corrected
    
    Output:
    Returns a matrix with x,y coordinates of matching points
    ###################################################################################################################
    '''
        
    detector = cv2.FeatureDetector_create("SURF") 
    descriptor = cv2.DescriptorExtractor_create("BRIEF")
    matcher = cv2.DescriptorMatcher_create("BruteForce-Hamming")
    
    # detect keypoints
    kp1 = detector.detect(img1)
    kp2 = detector.detect(img2)
    
    # descriptors
    k1, d1 = descriptor.compute(img1, kp1)
    k2, d2 = descriptor.compute(img2, kp2)
    
    # match the keypoints
    matches = matcher.match(d1, d2)
    
    # visualize the matches
    dist = [m.distance for m in matches] #extract the distances
    a=sorted(dist) #order the distances
    fildist=np.zeros(1) #use 1 in order to select the most reliable matches
    
    for i in range(0,1):
        fildist[i]=a[i]
    thres_dist = max(fildist)
    # keep only the reasonable matches
    sel_matches = [m for m in matches if m.distance <= thres_dist] 
    
    i=0
    points=np.zeros(shape=(len(sel_matches),4))
    for m in sel_matches:
        #matrix containing coordinates of the matching points
        points[i][:]= [int(k1[m.queryIdx].pt[0]),int(k1[m.queryIdx].pt[1]),int(k2[m.trainIdx].pt[0]),int(k2[m.trainIdx].pt[1])]
        i=i+1
    #print 'Feature Extraction - Done'
    return points 

def Offset_Comp(k1,k2,k3):
    
    xoff1=np.zeros(len(k1)) 
    xoff2=np.zeros(len(k2))
    xoff3=np.zeros(len(k3))
    
    yoff1=np.zeros(len(k1))
    yoff2=np.zeros(len(k2))
    yoff3=np.zeros(len(k3))
    
    #Offset calculation band1
    for l in range(0,len(k1)):
        xoff1[l]=k1[l][2]-k1[l][0]
        yoff1[l]=k1[l][3]-k1[l][1]
   
    #Offset calculation band2
    for l in range(0,len(k2)):
        xoff2[l]=k2[l][2]-k2[l][0]
        yoff2[l]=k2[l][3]-k2[l][1]
    
    #Offset calculation band3
    for l in range(0,len(k3)):
        xoff3[l]=k3[l][2]-k3[l][0]
        yoff3[l]=k3[l][3]-k3[l][1]
        
    #Final offset calculation - mean of calculated offsets
    xoff=round((xoff1.mean()+xoff2.mean()+xoff3.mean())/3)
    yoff=round((yoff1.mean()+yoff2.mean()+yoff3.mean())/3)
    
    print 'Offset: ' + str(xoff) + ', ' + str(yoff)
    
    return xoff,yoff


def shift_comp(path,folder1,folder2,shapefile,k1,k2,k3):
    
    '''
    ###################################################################################################################
    Calculation of shift using 3 different bands for each acquisition; the feature extraction algorithm is used to extract features
    
    Input:
     - path: path to the files
     - folder1: name of the folder containing the first acquisition (reference images)
     - folder2: name of the folder containing the second acquisition
     - shapefile: path to the shapefile used to clip the image
     
    Output: 
    Output file is in the same folder as the original file and is called "original_name_adj.TIF"
    
    Notes: 
    The input files are supposed to be landsat files with STANDARD NAMES (example "LT51800331991183XXX01_B1.TIF") modified by OUR CLIP ALGORITHM (example "LT51800331991183XXX01_B1_city.TIF").
    This procedure has been selected in order to facilitate the user.
    ###################################################################################################################
    '''
            
    xoff1=np.zeros(len(k1)) 
    xoff2=np.zeros(len(k2))
    xoff3=np.zeros(len(k3))
    
    yoff1=np.zeros(len(k1))
    yoff2=np.zeros(len(k2))
    yoff3=np.zeros(len(k3))
    
    #Offset calculation band1
    for l in range(0,len(k1)):
        xoff1[l]=k1[l][2]-k1[l][0]
        yoff1[l]=k1[l][3]-k1[l][1]
   
    #Offset calculation band2
    for l in range(0,len(k2)):
        xoff2[l]=k2[l][2]-k2[l][0]
        yoff2[l]=k2[l][3]-k2[l][1]
    
    #Offset calculation band3
    for l in range(0,len(k3)):
        xoff3[l]=k3[l][2]-k3[l][0]
        yoff3[l]=k3[l][3]-k3[l][1]
        
    #Final offset calculation - mean of calculated offsets
    xoff=round((xoff1.mean()+xoff2.mean()+xoff3.mean())/3)
    yoff=round((yoff1.mean()+yoff2.mean()+yoff3.mean())/3)
    
    print 'Offset: ' + str(xoff) + ', ' + str(yoff)
    
    '''
    Computing initial and final pixel for submatrix extraction.
    For each band a new matrix is created with rows+2*yoff and cols+2*xoff, filled with zeros where no original pixel values are available.
    The algorithm extracts a submatrix with same dimensions as the original image but changing the starting point using the calculated offset:
    - in case of negative offset the submatrix is going to start from (0,0)
    - in case of positive index the starting point is (2*off,2*yoff) because of the new dimensions
    '''
    
    if (xoff<=0):
        xstart=0
    else:
        xstart=2*xoff
        
    if (yoff<=0):
        ystart=0
    else:
        ystart=2*yoff
    
    band_files = os.listdir(path + folder2) #list files inside the directory
    #print band_files
    for j in range(1,9):
        band_file = [s for s in band_files if "B"+str(j)+"_city" in s]
        if band_file:
            inputimg2 = osgeo.gdal.Open(folder2+band_file[0],GA_ReadOnly) #open the image
            #print inputimg2
            if inputimg2 is None:
                print 'Could not open ' + band_file[0]
                sys.exit(1)
            cols2=inputimg2.RasterXSize #number of columns
            rows2=inputimg2.RasterYSize #number of rows
            band2 = inputimg2.RasterCount #number of bands
            geotransform=inputimg2.GetGeoTransform() #get geotransformation from the original image
            inprj=inputimg2.GetProjection() #get projection from the original image
            out=np.zeros(shape=(rows2,cols2)) #empty matrix
            driver=inputimg2.GetDriver()
            if os.path.isfile(folder2+band_file[0][:-4]+'_adj.TIF') == True:
                os.remove(folder2+band_file[0][:-4]+'_adj.TIF')
            output=driver.Create(folder2+band_file[0][:-4]+'_adj.TIF',cols2,rows2,band2) #create the output multispectral image
            inband2=inputimg2.GetRasterBand(1)
            outband=output.GetRasterBand(1)
            data2 = inband2.ReadAsArray()
            if j==8: #panchromatic band, dimensions of the panchromatic are different
                xoff = xoff*2
                yoff = yoff*2
                if (xoff<=0):
                    xstart=0
                else:
                    xstart=2*xoff
    
                if (yoff<=0):
                    ystart=0
                else:
                    ystart=2*yoff
            xend=xstart+cols2
            yend=ystart+rows2
    
            data2=np.c_[np.zeros((rows2,np.abs(xoff))),data2,np.zeros((rows2,np.abs(xoff)))] #add columns of zeros depending on the value of xoff around the original data
            data2=np.r_[np.zeros((np.abs(yoff),cols2+2*np.abs(xoff))),data2,np.zeros((np.abs(yoff),cols2+2*np.abs(xoff)))] #add rows of zeros depending on the value of yoff around the original data
            out=data2[int(ystart):int(yend),int(xstart):int(xend)] #submatrix extraction
            outband.WriteArray(out,0,0) #write to output image
            output.SetGeoTransform(geotransform) #set the transformation
            output.SetProjection(inprj)   #set the projection
            print 'Output: ' + band_file[0][:-4] + '_adj.TIF created' #output file created
        #inputimg2=None
        #output=None
        
'''      
def classification(path,folder,n_class,location,mapset,min_class,max_class):
'''
'''
    ###################################################################################################################
    Unsupervised classification of an image using GRASS - MAPSET HAS TO BE CREATED BEFORE EXECUTING THIS FUNCTION
    
    Input:
    - path: path to input folder
    - folder: name of the input folder, is used as part of the output name
    - n_class: number of classes to extract
    - location: grass parameter about the desired location to use
    - mapset: grass parameter about the mapset to be used
    - min_class: minimum value of the classes to select as a mask
    - max_class: maximum value of the classes to select as a mask
    
    Output:
    A file called uclasspy_folder_n_classes is added to the mapset - example "uclasspy_LT51800331984164XXX04_4"
    A file called uclasspy_folder_n_classes.TIF is added to the original folder - "uclasspy_LT51800331984164XXX04_4.TIF"
    ###################################################################################################################
'''
'''
    #GRASS details, mapset has to be created before
    if os.name == 'posix':
        #GRASS details, mapset has to be created before
        gisbase = 'C:\Program Files (x86)\GRASS GIS 6.4.3RC2'
        gisdbase = 'C:\grassdata'
    else:
        gisbase = 'C:\Program Files (x86)\GRASS GIS 6.4.3RC2'
        gisdbase = 'C:\grassdata'
    
    #Initialize GRASS session
    gsetup.init(gisbase, gisdbase, location, mapset)
    #Print list of mapsets in location
    m = grass.mapsets(False)
    
    #Set GRASS region to DEFAULT and print GRASS region extent
    grass.run_command("g.region", flags = 'd')
    r = grass.read_command("g.region", flags = 'p')
    filename = 'urban_area'
    
    #define the output file name
    output_name = 'uclasspy_' + folder + '_' + str(n_class)
    #define the group name
    group_name = 'g_'+folder
    #define the subgroup name
    subgroup_name = 'sub' + group_name
    #define the signature file name
    sigfile_name = group_name + '_sign_'  + str(n_class)
    band_files = os.listdir(path + folder) #list files inside the directory
    b1_file = [s for s in band_files if "B1_city_adj" in s]
    b2_file = [s for s in band_files if "B2_city_adj" in s]
    b3_file = [s for s in band_files if "B3_city_adj" in s]
    b4_file = [s for s in band_files if "B4_city_adj" in s]
    b5_file = [s for s in band_files if "B5_city_adj" in s]
    b6_file = [s for s in band_files if "B6_city_adj" in s]
    b7_file = [s for s in band_files if "B7_city_adj" in s]
    
    if not b1_file or not b2_file or not b3_file or not b4_file or not b5_file or not b6_file or not b7_file:
        b1_file = [s for s in band_files if "B1_city" in s]
        b2_file = [s for s in band_files if "B2_city" in s]
        b3_file = [s for s in band_files if "B3_city" in s]
        b4_file = [s for s in band_files if "B4_city" in s]
        b5_file = [s for s in band_files if "B5_city" in s]
        b6_file = [s for s in band_files if "B6_city" in s]
        b7_file = [s for s in band_files if "B7_city" in s]
        
    #remove mapsets with the same if existing
    grass.run_command("g.remove", rast = output_name)
    grass.run_command("g.remove", rast = sigfile_name)
    grass.run_command("g.remove", rast = folder+'_B1_city_adj')
    grass.run_command("g.remove", rast = folder+'_B2_city_adj')
    grass.run_command("g.remove", rast = folder+'_B3_city_adj')
    grass.run_command("g.remove", rast = folder+'_B4_city_adj')
    grass.run_command("g.remove", rast = folder+'_B5_city_adj')
    grass.run_command("g.remove", rast = folder+'_B6_city_adj')
    grass.run_command("g.remove", rast = folder+'_B7_city_adj')
    
    
    #add raster files to mapset
    grass.run_command("r.in.gdal", input = path+folder+separator+b1_file[0], output = folder+'_B1_city_adj', flags = 'k')
    grass.run_command("r.in.gdal", input = path+folder+separator+b2_file[0], output = folder+'_B2_city_adj', flags = 'k')
    grass.run_command("r.in.gdal", input = path+folder+separator+b3_file[0], output = folder+'_B3_city_adj', flags = 'k')
    grass.run_command("r.in.gdal", input = path+folder+separator+b4_file[0], output = folder+'_B4_city_adj', flags = 'k')
    grass.run_command("r.in.gdal", input = path+folder+separator+b5_file[0], output = folder+'_B5_city_adj', flags = 'k')
    grass.run_command("r.in.gdal", input = path+folder+separator+b6_file[0], output = folder+'_B6_city_adj', flags = 'k')
    grass.run_command("r.in.gdal", input = path+folder+separator+b7_file[0], output = folder+'_B7_city_adj', flags = 'k')
        
    #Set current grass region to input
    grass.run_command("g.region", rast = folder+'_B1_city_adj')
    #create a group
    #grass.run_command("i.group", group = group_name, subgroup = subgroup_name, input = 'mul_'+folder+'.1@'+mapset+',mul_'+folder+'.2@'+mapset+',mul_'+folder+'.3@'+mapset)
    grass.run_command("i.group", group = group_name, subgroup = subgroup_name, input = folder+'_B1_city_adj@'+mapset+','+folder+'_B2_city_adj@'+mapset+','+folder+'_B3_city_adj@'+mapset+','+folder+'_B4_city_adj@'+mapset+','+folder+'_B5_city_adj@'+mapset+','+folder+'_B6_city_adj@'+mapset+','+folder+'_B7_city_adj@'+mapset)
    
    #cluster function
    grass.run_command("i.cluster", group = group_name, subgroup = subgroup_name, sigfile = sigfile_name, classes = n_class)
    
    #maximum likelihood function, os.system is used because of the python conflict with the class name
    os.system("i.maxlik group="+ group_name + ' subgroup=' + subgroup_name + ' class=' + output_name + ' sigfile=' + sigfile_name + ' --v')
    grass.run_command("r.out.gdal", input=output_name, output=path+folder+separator+output_name+'.TIF', format='GTiff') #create the output image
    osgeo.gdal.AllRegister()
    inb = osgeo.gdal.Open(path+folder+separator+output_name+'.TIF', GA_ReadOnly)
    print str(path+folder+separator+output_name+'.TIF')
    inband = inb.GetRasterBand(1)
    data = inband.ReadAsArray()
    mask_class1 = np.greater_equal(data,min_class)
    mask_class2 = np.less_equal(data,max_class)
    mask_class = mask_class1*mask_class2
    classification_list=[]
    classification_mask = np.choose(mask_class,(0,1))
    classification_list.append(classification_mask)
    WriteOutputImage(folder+separator+output_name+'.TIF',path,'',folder+separator+'classification_mask_' + folder[9:13]+'.TIF',0,0,0,1,classification_list)
    del classification_list
'''
def urban_development_landsat(mat_data2,mat_data3,mat_data4,mat_data5,mat_data7):
    
    '''
    ###################################################################################################################
    Calculates the urban_index index helping the user to define a threshold
    
    Input:
    - path: path to the input file folder
    - folder: name of the input folder
    
    Output:
    Returns a matrix containing the urban_index values
    ###################################################################################################################
    '''
    
    print 'Urban Area Extraction'
    MNDWI = ((mat_data2-mat_data5) / (mat_data2+mat_data5+0.0001)) #compute the urban_index
    NDBI = ((mat_data5 - mat_data4) / (mat_data5 + mat_data4+0.0001))
    #NBI = ((mat_data3 * mat_data5) / (mat_data4+0.0001))
    #NDVI = ((mat_data4 - mat_data3) / (mat_data4 + mat_data3+0.0001))
    SAVI = (((mat_data4 - mat_data3)*(8+0.5)) / (mat_data3 + mat_data4+0.0001+0.5))
    #NDISI = ((mat_data6 - ((mat_data1 + mat_data4 + mat_data5)/3)) / (mat_data6 + ((mat_data1 + mat_data4 + mat_data5)/3)))
    Built_up = ((mat_data7+mat_data2 - 1.5*mat_data5) / (mat_data2 + mat_data5 + mat_data7+0.0001))# my built up indicator positive for builtup and negative for mountains 
    
    return  SAVI, NDBI, MNDWI, Built_up 
    
    
def pca(bandList):
    
    '''
    ###################################################################################################################
    Computes the Principal Component Analysis - Used in urban area extraction, good results with mode and third order component
    
    Input:
    - path: path to the input file folder
    - folder: input file folder
    
    Output:
    - immean: mean of all the bands
    - mode: first order component
    - sec_order: second order component
    - third_order: third order component
    ###################################################################################################################
    '''
    
    rows,cols = bandList[0].shape    
    #expand the listclass
    immatrix = np.array([np.array(bandList[i]).flatten() for i in range(1,7)],'f')
    
    #get dimensions
    num_data,dim = immatrix.shape

    #center data
    img_mean = immatrix.mean(axis=0)
    
    for i in range(num_data):
        immatrix[i] -= img_mean
    
    if dim>100:
        print 'PCA - compact trick used'
        M = np.dot(immatrix,immatrix.T) #covariance matrix
        e,EV = np.linalg.eigh(M) #eigenvalues and eigenvectors
        tmp = np.dot(immatrix.T,EV).T #this is the compact trick
        V = tmp[::-1] #reverse since last eigenvectors are the ones we want
        S = np.sqrt(e)[::-1] #reverse since eigenvalues are in increasing order
    else:
        print 'PCA - SVD used'
        U,S,V = np.linalg.svd(immatrix)
        V = V[:num_data] #only makes sense to return the first num_data    

    immean = img_mean.reshape(rows,cols)
    mode = V[0].reshape(rows,cols)
    sec_order = V[1].reshape(rows,cols)
    third_order = V[2].reshape(rows,cols)       
    new_indicator = ((4*mode)+immean)    /(immean + mode+sec_order+third_order+0.0001)
    
    
    
    return immean,mode,sec_order,third_order, new_indicator


def WriteOutputImage(projection_reference,path,folder,output_name,cols,rows,type,nbands,array_list):
    
    '''
    ###################################################################################################################
    Writes one or more matrixes to an image file setting the projection
    
    Input:
    - projection_reference: path to the reference image used to get the projection
    - path: path to the input folder
    - folder: input file folder
    - output_name: name of the output image
    - cols: number of columns, in case set to 0 the number of columns is taken from the reference image
    - rows: number of rows, in case set to 0 the number of rows is taken from the reference image
    - type: type of data to be written into the output file, if 0 the default is GDT_FLoat32
    - nbands: number of bands to be written to the output file
    - array_list: list containing all the data to be written; each element of the list should be a matrix
    
    Output:
    Output file is created into the same folder of the reference
    ###################################################################################################################
    '''
    # create the output image using a reference image for the projection
    # type is the type of data
    # array_list is a list containing all the data matrixes; a list is used because could be more than one matrix (more than one band)
    # if cols and rows are not provided, the algorithm uses values from the reference image
    # nbands contains the number of bands in the output image
    #print ('len(array_list[0]',len(array_list[0]))
    
    if type == 0:
        type = GDT_Float32
    inb = osgeo.gdal.Open(projection_reference, GA_ReadOnly)
    driver = inb.GetDriver()
    if rows == 0 or cols == 0:
        rows = inb.RasterYSize
        cols = inb.RasterXSize
    #print rows,cols
    outDs = driver.Create(path+folder+output_name, cols, rows,nbands, type)
    if outDs is None:
        print 'Could not create ' + output_name
        sys.exit(1)
    for i in range(nbands): 
        outBand = outDs.GetRasterBand(i+1)
        
        outmatrix = array_list[i].reshape(rows,cols)
        outBand.WriteArray(outmatrix, 0, 0)
        
    # georeference the image and set the projection
    outDs.SetGeoTransform(inb.GetGeoTransform())
    outDs.SetProjection(inb.GetProjection())


def contours_extraction(input_image):
    
    '''
    ###################################################################################################################
    Finds the contours into an image
    
    Input:
    - input_image
    
    Output:
    A list containing points for the contours
    ###################################################################################################################
    '''
    import pylab
    img = cv2.imread(input_image)
    gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    ret,thresh = cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    #fg = cv2.erode(thresh,None,iterations = 2)
    #bgt = cv2.dilate(thresh,None,iterations = 3)
    #ret,bg = cv2.threshold(bgt,1,128,1)
    contours, hierarchy = cv2.findContours(thresh,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(img,contours,-1,(0,255,0),-1)
    #cv2.imshow('cont',img)
    pylab.imshow(img)
    pylab.show()
    return contours


def reproject_shapefile(path,name_input,name_output,epsg_output,option):
    
    '''
    ###################################################################################################################
    Reproject a shapefile
    
    Input:
    - input_image
    
    Output:
    A list containing points for the contours
    ###################################################################################################################
    '''
    if option == 'line':
        type = osgeo.ogr.wkbLineString
    if option == 'polygon':
        type = osgeo.ogr.wkbPolygon
    if option == 'point':
        type = osgeo.ogr.wkbPoint
    #print type    
    
    #Parameters
    os.chdir(path) #path for source files
    epsg_input = 4326
    #driver definition for shapefile
    driver=osgeo.ogr.GetDriverByName('ESRI Shapefile')
    
    #define an input and an output projection for the coordinate transformation
    inprj=osgeo.osr.SpatialReference()
    inprj.ImportFromEPSG(epsg_input)
    
    outprj=osgeo.osr.SpatialReference()
    outprj.ImportFromEPSG(epsg_output)
    
    newcoord=osgeo.osr.CoordinateTransformation(inprj,outprj)
    
    #select input file and create an output file
    infile=driver.Open(name_input+'.shp',0)
    inlayer=infile.GetLayer()
    
    outfile=driver.CreateDataSource(name_output+'.shp')
    outlayer=outfile.CreateLayer(name_input,geom_type=type)
    
    feature=inlayer.GetFeature(0)
    #feat = osgeo.ogr.Feature( inlayer.GetLayerDefn() )
    layer_defn = inlayer.GetLayerDefn() #get definitions of the layer
    field_names = [layer_defn.GetFieldDefn(i).GetName() for i in range(layer_defn.GetFieldCount())] #store the field names as a list of strings
    #print field_names
    for i in range(0,len(field_names)):
        field = feature.GetFieldDefnRef(field_names[i])
        outlayer.CreateField(field)
        
    # get the FeatureDefn for the output shapefile
    feature_def = outlayer.GetLayerDefn()
    
    # loop through the input features
    infeature = inlayer.GetNextFeature()
    while infeature:
        # get the input geometry
        geom = infeature.GetGeometryRef()
        # reproject the geometry
        geom.Transform(newcoord)
        # create a new feature
        outfeature = osgeo.ogr.Feature(feature_def)
        # set the geometry and attribute
        outfeature.SetGeometry(geom)
        #field_names = [layer_defn.GetFieldDefn(i).GetName() for i in range(layer_defn.GetFieldCount())]
        for i in range(0,len(field_names)):
            #print infeature.GetField(field_names[i])
            outfeature.SetField(field_names[i],infeature.GetField(field_names[i]))
            # add the feature to the shapefile
            outlayer.CreateFeature(outfeature)
    
            # destroy the features and get the next input feature
            outfeature.Destroy
            infeature.Destroy
            infeature = inlayer.GetNextFeature()

    # close the shapefiles
    infile.Destroy()
    outfile.Destroy()

    # create the *.prj file
    outprj.MorphToESRI()
    prjfile = open(name_output+'.prj', 'w')
    prjfile.write(outprj.ExportToWkt())
    prjfile.close()
  
def SLIC( Input_Image,rat, n_seg, sig, multiband_option):
    
    '''
    ###################################################################################################################
    Description:    Segments image using k-means clustering in Color space.

    source:         skimage, openCv python 
    
    parameters:     Input_Image : ndarray
                    Input image, which can be 2D or 3D, and grayscale or multi-channel (see multichannel parameter).
    
                    n_seg : number of segments, int
                    The (approximate) number of labels in the segmented output image.
    
                    rat:  ratio/compactness, float
                    Balances color-space proximity and image-space proximity. Higher values give more weight to color-space and yields more square regions
    
                    sig : sigma, float
                    Width of Gaussian smoothing kernel for preprocessing. Zero means no smoothing.
    
    return:         Output_mask : ndarray
                    Integer mask indicating segment labels.
    
    Reference: http://scikit-image.org/docs/0.9.x/api/skimage.segmentation.html?highlight=slic#skimage.segmentation.slic
    ###################################################################################################################    
    '''
    
    if rat == 0:
        rat = 0.1
    if n_seg == 0:
        n_seg = 300
    if sig ==0:
        sig = 1

    #img = cv2.imread(Input_Image)
    #segments_slic = slic(Input_Image, ratio=rat, n_segments=n_seg, sigma=sig)
    segments_slic = slic(Input_Image, n_segments = n_seg, compactness=0.1, max_iter=10, sigma=sig, spacing=None, multichannel=multiband_option)
    
    print("Slic number of segments: %d" % len(np.unique(segments_slic)))
    return segments_slic


def FELZENSZWALB(Input_Image, scale, sigma, min_size):
   
    '''
    ###################################################################################################################
    Description:   Computes Felsenszwalbs efficient graph based image segmentation. 

    source:         skimage, openCv python 
    
    parameters:     Input_Image : ndarray
                    Input image
    
                    min-size : int
                    Minimum component size. Enforced using postprocessing.
    
                    scale:  float
                     The parameter scale sets an observation level. Higher scale means less and larger segments.
    
                    sigma : float
                    Width of Gaussian smoothing kernel for preprocessing. Zero means no smoothing.
    
    return:         Segment_mask : ndarray
                    Integer mask indicating segment labels.
    
    Reference: http://scikit-image.org/docs/0.9.x/api/skimage.segmentation.html?highlight=felzenszwalb#skimage.segmentation.felzenszwalb
    ###################################################################################################################     
    '''
    #default values, set in case of 0 as input
    if scale == 0:
        scale = 5
    if sigma == 0:
        sigma = 0.5
    if min_size == 0:
        min_size = 30

    #print Input
    #img = cv2.imread(Input_Image)
    #print img
    #print img.shape

    segments_fz = felzenszwalb(Input_Image, scale, sigma, min_size)
    #print segments_fz.shape
    #print ('segments_fz datatype',segments_fz.dtype )
    print("Felzenszwalb's number of segments: %d" % len(np.unique(segments_fz)))
    print ('segments_fz datatype',segments_fz.dtype )

    return segments_fz



def QUICKSHIFT(Input_Image,ks, md, r):
        
    '''
    ###################################################################################################################
    Description:    Segments image using quickshift clustering in Color space.

    source:         skimage, openCv python 
    
    parameters:     Input_Image : ndarray
                    Input image
    
                    kernel size : float
                    Width of Gaussian kernel used in smoothing the sample density. Higher means fewer clusters.
    
                    max distance:  float
                    Cut-off point for data distances. Higher means fewer clusters.
    
                    ratio : float, between 0 and 1 
                    Balances color-space proximity and image-space proximity. Higher values give more weight to color-space.
    
    return:         Segment_mask : ndarray (cols, rows)
                    Integer mask indicating segment labels.
                    
    Reference: http://scikit-image.org/docs/0.9.x/api/skimage.segmentation.html?highlight=quickshift#skimage.segmentation.quickshift
    ###################################################################################################################
    '''
    
    #default values, set in case of 0 as input
    if ks == 0:
        ks = 5
    if md == 0:
        md = 10
    if r == 0:
        r = 1
    # print kernel_size,max_dist, ratio    
    #img = cv2.imread(Input_Image)
    segments_quick = quickshift(Input_Image, kernel_size=ks, max_dist=md, ratio=r)
    #print segments_quick.shape
    print("Quickshift number of segments: %d" % len(np.unique(segments_quick)))
    return segments_quick


def WATERSHED(Input_Image):
    
    '''
    ###################################################################################################################
    Description:    Computes watershed segmentation,based on mathematical morphology and flooding of regions from markers.

    source:         openCV 
    
    parameters:     Input_Image : ndarray
                    Input image
    
                   marker: float
                
    return:         Segment_mask : ndarray (cols, rows)
                    Integer mask indicating segment labels.
                    
    Reference: http://docs.opencv.org/modules/imgproc/doc/miscellaneous_transformations.html?highlight=watershed#cv2.watershed
    ###################################################################################################################
    '''   
    # read the input image
    print Input_Image
    img = cv2.imread(Input_Image,cv2.COLOR_BGR2GRAY)
    print img.shape
    #pylab.imshow(img)
    #pylab.show()
    '''
    #img = Input_Image
    # convert to grayscale
    g1 = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

    # smooth the image 
    g = cv2.medianBlur(g1,5)

    # Apply adaptive threshold
    thresh1 = cv2.adaptiveThreshold(g,255,1,1,11,2)
    thresh_color = cv2.cvtColor(thresh1,cv2.COLOR_GRAY2BGR)

    # Apply  dilation and erosion 
    bgt = cv2.dilate(thresh1,None,iterations = 3)
    fg = cv2.erode(bgt,None,iterations = 2)
    
    #thresholding on the background
    ret,bg = cv2.threshold(bgt,1,128,1)
    
    #adding results
    marker = cv2.add(fg,bg)
    
    #moving markers to 32 bit signed single channel
    marker32 = np.int32(marker)
    
    #segmenting
    #cv2.watershed(Input_Image,marker32)
    cv2.watershed(img,marker32)
    m = cv2.convertScaleAbs(marker32)

    ret,thresh = cv2.threshold(m,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    res = cv2.bitwise_and(img,img,mask = thresh)
    segments_watershed = cv2.cvtColor(res, cv2.COLOR_BGR2GRAY)
    print("watershed number of segments: %d" % len(np.unique(segments_watershed)))
    segments_watershed = segments_watershed.astype(np.int32)
    #print ('segments_watershed datatype',segments_watershed.dtype )
    '''
    return img


def Pixel2world(gt, cols, rows ):
    '''
    Description: Uses a gdal geomatrix  to calculate  the geospatial coordinates of top-left and down-right pixel  
    '''
    
    minx = gt[0]
    miny = gt[3] + cols*gt[4] + rows*gt[5] 
    maxx = gt[0] + cols*gt[1] + rows*gt[2]
    maxy = gt[3] 
    
    
    return (maxx,miny)


def BAATZ(Input,Folder,exe,euc_threshold,compactness,baatz_color,scale,multiband_option):#,input_bands,input_weights,output folder,reliability):
    
    '''
    ###################################################################################################################
    
    Description:               performs a segmentation based on Baatz where each generated segment represents an hypothesis to be analyzed by the next semantic network node.
    
    Source:                    InterIMAGE 1.34, open source, the code is written in C++ 
                               http://interimage.sourceforge.net/
    
    parameters:    
              - Input_Image: 
                              The image to which the segmentation will be applied 
    
              - Folder: 
                              temporal folder, for working on the direct products of the segmentor   
              
              -exe_path: 
                              path to the attached excutive file 
              
              -euc_threshold: float, positive
                              The minimum Euclidean Distance between each segment feature.    
                                            
              -compactness:   float, between 0 and one 
                              Baatz Compactness Weight attribute 
              
              -baatz_color:   float, between 0 and one
                              Baatz Color Weight attribute 
                              
              -scale:         float, positive
                              Baatz scale attribute.
                              
              -multiband_option: True to compute the segmentation using all the bands
                                 False to compute the segmentatiob using just one band 
               
               Other parameters                            
              -input_bands:   String, a comma-separated list of used input images channels/bands (starting from 0)   
                              in this case we considered only the pancromatic band
              
              -input_weights: String, a comma-separated list of used input channels/bands weights.    
                              in this case we considered only one pancromatic band 
              
              -output folder: 
                              the folder containg the created segment_mask  ndarray (cols, rows)
              
              -reliability:   float, between 0 and one
                              The reliability (higher priority will be given to nodes with higher weights in cases where there are geographic overlays).
    
    return:   -Segment_mask : ndarray (cols, rows)
                              Integer mask indicating segment labels.
                              
    Reference: http://www.ecognition.cc/download/baatz_schaepe.pdf
    ###################################################################################################################
    '''
    
    #default values, set in case of 0 as input
    if euc_threshold == 0:
        euc_threshold = 50
    if compactness  == 0:
        compactness = 0.5
    if baatz_color  == 0:
        baatz_color = 0.5
    if scale  == 0:
        scale = 80
        
    # open the input file 
    ds = gdal.Open(Input, GA_ReadOnly)
    if ds is None:
        print 'Could not open image'
        sys.exit(1)
        
    # get image size
    rows = ds.RasterYSize
    cols = ds.RasterXSize
    nbands = ds.RasterCount
    
    if (multiband_option == True) and (nbands > 1):
        bands_str = ','.join(str(i) for i in xrange(nbands))
        weights_str = ','.join('1' for i in xrange(nbands))
    else:
        bands_str = '0'
        weights_str = '1'
        #print bands_str
        #print weights_str
    
    #get the coordinates the top left and down right pixels
    gt = ds.GetGeoTransform()
    #print gt[0], gt[3]  
    GW=gt[0]
    GN=gt[3]
    a= Pixel2world(gt, cols,rows)
    #print a[0], a[1]
    GE= a[0]
    GS= a[1]
    
    output_file = Folder + '\\'+'baatz'
    
    #removing the file created by the segmenter after each run
    Folder_files = os.listdir(Folder)
    file_ = [s for s in Folder_files if "ta_segmenter" in s]
    if file_:
        os.remove(Folder+'\\'+file_[0])
    exe_file =  exe +'\\'+ 'ta_baatz_segmenter.exe'   
    #runs the baatz segmenter
    os.system(exe_file + ' "'+Input+'" "'+str(GW)+'" "'+str(GN)+'" "'+str(GE)+'" "'+str(GS)+'" "" "'+Folder+'" "" Baatz "'+str(euc_threshold)+'" "@area_min@" "'+str(compactness)+'" "'+str(baatz_color)+'" "'+str(scale)+'" "'+str(bands_str)+ '" "' + str(weights_str)+'" "'+output_file+'" "seg" "0.2" "" "" "no"')

    #removing the raw file if existed
    if os.path.exists(output_file + '.raw'):
        os.remove(output_file +'.raw')
       
    os.chdir(Folder)
    
    
    
    #changing plm to raw
    output = output_file +'.plm'
    os.rename(output, output_file + ".raw")
    new_image = output_file + ".raw"
    
    
    #removing the header lines from the raw file
    with open(new_image, 'r+b') as f:
        lines = f.readlines()
    #print len(lines)
    
    lines[:] = lines[4:]
    with open(new_image, 'w+b') as f:
        f.write(''.join(lines))
    #print len(lines)
    f.close()

    ##memory mapping
    segments_baatz = np.memmap( new_image, dtype=np.int32, shape=(rows, cols))#uint8, float64, int32, int16, int64
    print("output_baatz's number of segments: %d" % len(np.unique(segments_baatz)))
    
    return segments_baatz


def REGION_GROWING(Input,Folder,exe,euc_threshold,compactness,baatz_color,scale,multiband_option):#,input_bands,input_weights,output folder,reliability)
    
    '''
    ###################################################################################################################
    Description:               performs a segmentation based on region growing based segmentation, where each generated segment represents an hypothesis to be analyzed by the next semantic network node.
    
    Source:                    InterIMAGE 1.34, open source, the code is written in C++ 
                               http://interimage.sourceforge.net/
    parameters:    
              - Input_Image: 
                              The image to which the segmentation will be applied 
    
              - Folder: 
                              temporal folder, for working on the direct products of the segmentor   
              
              -exe_path: 
                              path to the attached excutive file 
              
              -euc_threshold: float, positive
                              The minimum Euclidean Distance between each segment feature.    
                                            
              -compactness:   float, between 0 and one 
                              Region Growing Compactness Weight attribute 
              
              -baatz_color:   float, between 0 and one
                              Region Growing Color Weight attribute 
                              
              -scale:         float, positive
                              Region Growing scale attribute.
                              
              -multiband_option: True to compute the segmentation using all the bands
                                 False to compute the segmentatiob using just one band 
              
              Other parameters 
              -input_bands:   String, a comma-separated list of used input images channels/bands (starting from 0)   
                              in this case we considered only the pancromatic band
              
              -input_weights: String, a comma-separated list of used input channels/bands weights.    
                              in this case we considered only one pancromatic band 
              
              -output folder: 
                              the folder containg the created segment_mask  ndarray (cols, rows)
              
              -reliability:   float, between 0 and one
                              The reliability (higher priority will be given to nodes with higher weights in cases where there are geographic overlays).
    
    return:   -Segment_mask : ndarray (cols, rows)
                              Integer mask indicating segment labels.
                              
    Reference: http://marte.sid.inpe.br/col/sid.inpe.br/deise/1999/02.05.09.30/doc/T205.pdf
    ###################################################################################################################
    '''

    #default values, set in case of 0 as input
    if euc_threshold == 0:
        euc_threshold = 80
    if compactness  == 0:
        compactness = 0.5
    if baatz_color  == 0:
        baatz_color = 0.5
    if scale  == 0:
        scale = 80
    # open the input file 
    ds = gdal.Open(Input, GA_ReadOnly)
    if ds is None:
        print 'Could not open image'
        sys.exit(1)
        
    # get image size
    rows = ds.RasterYSize
    cols = ds.RasterXSize
    nbands = ds.RasterCount
    
    if (multiband_option == True) and (nbands > 1):
        bands_str = ','.join(str(i) for i in xrange(nbands))
        weights_str = ','.join('1' for i in xrange(nbands))
    else:
        bands_str = '0'
        weights_str = '1'
    #get the coordinates the top left and down right pixels
    gt = ds.GetGeoTransform()
    #print gt[0], gt[3]  
    GW=gt[0]
    GN=gt[3]
    a= Pixel2world(gt, cols,rows)
    #print a[0], a[1]
    GE= a[0]
    GS= a[1]
    output_file = Folder + '\\'+'regiongrowing'
    
    #removing the changing name file created by the segmenter after each run
    Folder_files = os.listdir(Folder)
    file_ = [s for s in Folder_files if "ta_segmenter" in s]
    if file_:
        os.remove(Folder+'\\'+file_[0])
    exe_file =  exe +'\\'+ 'ta_regiongrowing_segmenter.exe'   
    
    
    #runs the regiongrowing segmenter
    os.system(exe_file + ' "'+Input+'" "'+str(GW)+'" "'+str(GN)+'" "'+str(GE)+'" "'+str(GS)+'" "" "'+Folder+'" "" RegionGrowing "'+str(euc_threshold)+'" "@area_min@" "'+str(compactness)+'" "'+str(baatz_color)+'" "'+str(scale)+'" "'+str(bands_str)+ '" "' + str(weights_str)+'" "'+output_file+'" "seg" "0.2" "" "" "no"')

    #removing the raw file if existed
    if os.path.exists(output_file + '.raw'):
        os.remove(output_file +'.raw')
       
    os.chdir(Folder)
    
    #changing plm to raw
    output = output_file +'.plm'
    os.rename(output, output_file + ".raw")
    new_image = output_file + ".raw"
    
    
    #removing the header lines from the raw file
    with open(new_image, 'r+b') as f:
        lines = f.readlines()
    #print len(lines)
    
    lines[:] = lines[4:]
    with open(new_image, 'w+b') as f:
        f.write(''.join(lines))
    #print len(lines)
    f.close()
    
    
    #memory mapping
    segments_regiongrowing = np.memmap( new_image, dtype=np.int32, shape=(rows, cols))
    print("output_regiongrowing's number of segments: %d" % len(np.unique(segments_regiongrowing)))
    
    return segments_regiongrowing


def spectral_features(dn_value,input_data,seg_data):
    
    #result_list = []
    mean = 0.0
    std = 0.0
    mode = 0.0
    maxbr = 0.0
    minbr = 0.0
    mask = np.equal(seg_data,dn_value)
    seg_pos = np.where(seg_data==dn_value)
    mat_pos = np.zeros(len(seg_pos[0]))
    for l in range(0,len(seg_pos[0])):
        mat_pos[l] = input_data[seg_pos[0][l]][seg_pos[1][l]]
    mean = mat_pos.mean()
    std = mat_pos.std()
    maxbr = np.amax(mat_pos)
    minbr = np.amin(mat_pos)
    mode_ar = scipy.stats.mode(mat_pos)
    mode = mode_ar[0][0]
    mat_pos=None
    seg_pos=None
    mask=None
    return mean,std,maxbr,minbr,mode


def multispectral_features(dn_value,band_sum,ndvi,seg_data,nbands):
    
    ndvi_mean = 0.0
    ndvi_std = 0.0
    wb = 0.0
    div = 1.0
    
    mask = np.equal(seg_data,dn_value)
    #print mask.shape
    outmask_band_sum = np.choose(mask,(0,band_sum)) 
    seg_pos = np.where(seg_data==dn_value)
    ndvi_pos = np.zeros(len(seg_pos[0]))
    for l in range(0,len(seg_pos[0])):
        ndvi_pos[l] = ndvi[seg_pos[0][l]][seg_pos[1][l]]
    npixels = np.sum(mask)
    nzeros = np.size(outmask_band_sum)-npixels

    values = np.sum(outmask_band_sum)
    nbp = nbands*npixels
    div = 1.0/nbp
            
    ndvi_mean = ndvi_pos.mean()
    ndvi_std = ndvi_pos.std()
    wb = div*values
    
    return ndvi_mean,ndvi_std,wb



def textural_features(dn_value,input_data,seg_data):
    
    contrast = 0.0
    energy = 0.0
    dissimilarity = 0.0
    homogeneity = 0.0
    correlation = 0.0
    ASM = 0.0
    mask = np.equal(seg_data,dn_value)
    seg_pos = np.where(seg_data==dn_value)
    xstart = np.amin(seg_pos[1])
    xend = np.amax(seg_pos[1])
    ystart = np.amin(seg_pos[0])
    yend = np.amax(seg_pos[0])
    data_glcm = np.zeros((yend-ystart+1,xend-xstart+1))
    data_glcm = input_data[ystart:yend+1,xstart:xend+1]
    
    glcm = greycomatrix(data_glcm, [1], [0], levels=256, symmetric=False, normed=True)
    contrast= greycoprops(glcm, 'contrast')[0][0]
    energy= greycoprops(glcm, 'energy')[0][0]
    homogeneity= greycoprops(glcm, 'homogeneity')[0][0]
    correlation=greycoprops(glcm, 'correlation')[0][0]
    dissimilarity=greycoprops(glcm, 'dissimilarity')[0][0]
    ASM=greycoprops(glcm, 'ASM')[0][0]
    
    return contrast,energy,homogeneity,correlation,dissimilarity,ASM
 

def homogeneity_mov_window(input_data):
    
    from skimage.util.shape import view_as_windows
    homogeneity = 0.0
    dissimilarity = 0.0
    rows,cols=input_data[0].shape
    print input_data[0].shape
    output_homogeneity = np.zeros((rows,cols)).astype(np.float32)
    output_homogeneity2 =np.zeros((rows,cols)).astype(np.float32)
    output_dissimilarity = np.zeros((rows,cols)).astype(np.float32)
    output_dissimilarity2 = np.zeros((rows,cols)).astype(np.float32)
    rows = rows-2
    cols = cols-1
    #window = (5,5)
    #data_glcm=window_stack(input_data,stepsize=1,width=5)
    
    for i in range(0,cols):
        print str(i)+' of '+str(rows)
        for j in range(0,cols):
            #print str(j)+' of '+str(cols)
            data_glcm_1 = input_data[0][i:i+5,j:j+5]
            data_glcm_2 = input_data[1][i:i+5,j:j+5]
            if (i+5<rows) and (j+5<cols):
                glcm1 = greycomatrix(data_glcm_1, [1], [0], levels=256, symmetric=False, normed=True)
                homogeneity= greycoprops(glcm1, 'homogeneity')[0][0]
                dissimilarity=greycoprops(glcm1, 'dissimilarity')[0][0]
                #print homogeneity,dissimilarity
                index_row = i+2
                index_col = j+2
                output_homogeneity[index_row][index_col]=float(homogeneity)
                output_dissimilarity[i+2][j+2]=float(dissimilarity)
                
                glcm2 = greycomatrix(data_glcm_2, [1], [0], levels=256, symmetric=False, normed=True)
                homogeneity2= greycoprops(glcm2, 'homogeneity')[0][0]
                dissimilarity2=greycoprops(glcm2, 'dissimilarity')[0][0]
                output_homogeneity2[index_row][index_col]=float(homogeneity2)
                output_dissimilarity2[i+2][j+2]=float(dissimilarity2)
                #print data_glcm.shape
                #print homogeneity
                
    #print output_homogeneity[2][2],output_homogeneity[2][3],output_homogeneity[0][0]
    
    #print output_dissimilarity
    #data_glcm = view_as_windows(input_data,window,step=1)
    #data_list2 = [tuple(data_list[i][j]) for i in range(0,len(data_list)) for j in range(0,len(data_list[i]))]
    #print data_list2
    #result=map(greycomatrix(data_glcm, [1], [0], levels=256, symmetric=False, normed=True),data_glcm)
    #print len(result)
    #print data_list
    #soutput_homogeneity.astype(np.float32)
    #print output_homogeneity.dtype.name
    return output_homogeneity,output_dissimilarity,output_homogeneity2,output_dissimilarity2
    
    
def call_multiprocess(process,parameters_list,first_segment,last_segment):
    
    processors = multiprocessing.cpu_count()
    pool = Pool(processes=processors)
    interval = (last_segment-first_segment+1)/processors
    result_list=[]
    #print parameters_list
    if processors == 2:
        parameters_first = []
        parameters_second = []
        
        #print len(parameters_list)
        #print len(parameters_list[0]),len(parameters_list[1]),len(parameters_list[2])
        for i in range(0,len(parameters_list)):
            parameters_first.append(parameters_list[i])
            parameters_second.append(parameters_list[i])
        
        start_first = int(first_segment)
        end_first = int(first_segment+interval)
        #print start_first,end_first
        start_second = int(end_first)
        end_second = int(last_segment+1)
        #print start_second,end_second
        
        parameters_first.append(start_first)
        parameters_first.append(end_first)
        parameters_second.append(start_second)
        parameters_second.append(end_second)
        result_list = pool.map(process,((parameters_first),(parameters_second)))
        
    if processors == 4:
        parameters_first = []
        parameters_second = []
        parameters_third = []
        parameters_fourth = []
        
        for i in range(0,len(parameters_list)):
            parameters_first.append(parameters_list[i])
            parameters_second.append(parameters_list[i])
            parameters_third.append(parameters_list[i])
            parameters_fourth.append(parameters_list[i])
        
        start_first = int(first_segment)
        end_first = int(first_segment+interval)
        #print start_first,end_first
        start_second = int(end_first)
        end_second = int(end_first+interval)
        
        start_third = int(end_second)
        end_third = int(end_second+interval)
        
        start_fourth = int(end_third)
        end_fourth = int(last_segment+1)
        
        parameters_first.append(start_first)
        parameters_first.append(end_first)
        parameters_second.append(start_second)
        parameters_second.append(end_second)
        parameters_third.append(start_third)
        parameters_third.append(end_third)
        parameters_fourth.append(start_fourth)
        parameters_fourth.append(end_fourth)
        result_list = pool.map(process,((parameters_first),(parameters_second),(parameters_third),(parameters_fourth)))
    
    return result_list
    
    
def Read_Image(path,data_type):
    
    '''
    ###################################################################################################################
    Reads all the bands of an input image using GDAL
    
    Input:
    - path: path of the input image 
    - data_type: type of data to force; for example np.uint16, np.uint8 or np.float32.
        Default is np.uint16
    
    Output:
    A list is returned containing rows, columns, number of bands, list of matrices related to each band, geo-transformation and projection (in this order)
    ###################################################################################################################
    '''
    
    band_list = []
    if data_type == 0:
        data_type = np.uint16
        
    inputimg = osgeo.gdal.Open(path, GA_ReadOnly)
    cols=inputimg.RasterXSize
    rows=inputimg.RasterYSize
    nbands=inputimg.RasterCount
    
    for i in range(1,nbands+1):
        inband = inputimg.GetRasterBand(i)
        mat_data = inband.ReadAsArray().astype(data_type)
        band_list.append(mat_data)
    
    geo_transform = inputimg.GetGeoTransform()
    projection = inputimg.GetProjection()
    return rows,cols,nbands,band_list,geo_transform,projection


def Read_Image_Parameters(path):
    
    '''
    ###################################################################################################################
    Reads all paramters related to an image using GDAL. Used to save time in respect of the Read_Image function
    
    Input:
    - path: path of the input image 
    
    Output:
    A list is returned containing rows, columns, number of bands, geo-transformation and projection (in this order)
    ###################################################################################################################
    '''
   
    inputimg = osgeo.gdal.Open(path, GA_ReadOnly)
    cols=inputimg.RasterXSize
    rows=inputimg.RasterYSize
    nbands=inputimg.RasterCount
    
    geo_transform = inputimg.GetGeoTransform()
    projection = inputimg.GetProjection()
    return rows,cols,nbands,geo_transform,projection


def pansharp(input_multiband,input_panchromatic,output_folder,output_name):
    
    '''
    ###################################################################################################################
    Performs the pan-sharpening process using OTB library
    
    Input:
    - input_multiband: path to the multispectral image
    - input_panchromatic: path to the panchromatic image
    - output_folder: path to output folder, used to save the resampled image
    - output_name: name of the output pan-sharpened file
    
    Output:
    Nothing is returned. Output image is automatically saved.
    ###################################################################################################################
    '''
    
    rowsp,colsp,nbands,geo_transform,projection = Read_Image_Parameters(input_panchromatic)
    rowsxs,colsxs,nbands,geo_transform,projection = Read_Image_Parameters(input_multiband)
    
    scale_rows = round(float(rowsp)/float(rowsxs),2)
    scale_cols = round(float(colsp)/float(colsxs),2)
    
    RigidTransformResample = otbApplication.Registry.CreateApplication("RigidTransformResample") 
    # The following lines set all the application parameters: 
    RigidTransformResample.SetParameterString("in", input_multiband) 
    RigidTransformResample.SetParameterString("out", output_folder + "resampled.tif") 
    RigidTransformResample.SetParameterString("transform.type","id") 
    RigidTransformResample.SetParameterFloat("transform.type.id.scalex", scale_cols) 
    RigidTransformResample.SetParameterFloat("transform.type.id.scaley", scale_rows) 
    RigidTransformResample.SetParameterInt("ram", 2000)
    RigidTransformResample.ExecuteAndWriteOutput()
 
    Pansharpening = otbApplication.Registry.CreateApplication("Pansharpening") 
    # Application parameters
    Pansharpening.SetParameterString("inp", input_panchromatic) 
    Pansharpening.SetParameterString("inxs", output_folder + "resampled.tif") 
    Pansharpening.SetParameterInt("ram", 2000) 
    Pansharpening.SetParameterString("out", output_folder + output_name) 
    Pansharpening.SetParameterOutputImagePixelType("out", 3) 
     
    Pansharpening.ExecuteAndWriteOutput()
    

def watershed_otb(input_img,output_file,output_mode,threshold,level):    
    
    '''
    ###################################################################################################################
    Performs the watershed segmentation using OTB library
    
    Input:
    - input_image: path to the input image
    - output_file: path and name of the output file (raster or vector)
    - output_mode: 'raster' or 'vector' as a string
    - threshold: '0' for default value, float
    - level: '0' for default value, float
    
    Output:
    Nothing is returned. Output image is automatically saved.
    
    Reference: http://orfeo-toolbox.org/CookBook/CookBooksu113.html#x144-9030004.9.6
    ###################################################################################################################
    '''

    Segmentation = otbApplication.Registry.CreateApplication("Segmentation")
    Segmentation.SetParameterString("in", input_img)
    Segmentation.SetParameterString("mode",output_mode)
    Segmentation.SetParameterString("mode."+output_mode+".out", output_file)
    Segmentation.SetParameterString("filter","watershed")
    if (threshold!=0):
        Segmentation.SetParameterFloat("filter.watershed.threshold",threshold)
    if (level!=0):
        Segmentation.SetParameterFloat("filter.watershed.level",level)
        
    Segmentation.ExecuteAndWriteOutput()
    
    
def meanshift_otb(input_img,output_file,output_mode,spatial_radius,range_radius,threshold,max_iter,min_size):
    
    '''
    ###################################################################################################################
    Performs the meanshift segmentation using OTB library
    
    Input:
    - input_image: path to the input image
    - output_file: path and name of the output file (raster or vector)
    - output_mode: 'raster' or 'vector' as a string
    - spatial_radius: spatial radius, '0' for default value, int
    - range_radius: range radius, '0' for default value, float
    - threshold: mode convergence threshold, '0' for default value, float
    - max_iter: maximum number of iterations, '0' for default value, int
    - min_size: minimum region size, '0' for default value, int
    
    Output:
    Nothing is returned. Output image is automatically saved.
    
    Reference: http://orfeo-toolbox.org/CookBook/CookBooksu113.html#x144-9030004.9.6
    ###################################################################################################################
    ''' 
    
    
    Segmentation = otbApplication.Registry.CreateApplication("Segmentation")
    Segmentation.SetParameterString("in", input_img)
    Segmentation.SetParameterString("mode",output_mode)
    Segmentation.SetParameterString("mode."+output_mode+".out", output_file)
    Segmentation.SetParameterString("filter","meanshift")
    if (spatial_radius!=0):
        Segmentation.SetParameterInt("filter.meanshift.spatialr",spatial_radius)
    if (range_radius!=0):
        Segmentation.SetParameterFloat("filter.meanshift.ranger",range_radius)
    if (threshold!=0):
        Segmentation.SetParameterFloat("filter.meanshift.thres",threshold)
    if (max_iter!=0):
        Segmentation.SetParameterInt("filter.meanshift.maxiter",max_iter)
    if (min_size!=0):
        Segmentation.SetParameterInt("filter.meanshift.minsize",min_size)

    Segmentation.ExecuteAndWriteOutput()
    
    
def edison_otb(input_img,output_file,output_mode,spatial_radius,range_radius,min_size,scale):
    
    '''
    ###################################################################################################################
    Performs the edison-meanshift segmentation using OTB library
    
    Input:
    - input_image: path to the input image
    - output_file: path and name of the output file (raster or vector)
    - output_mode: 'raster' or 'vector' as a string
    - spatial_radius: spatial radius, '0' for default value, int
    - range_radius: range radius, '0' for default value, float
    - min_size: minimum region size, '0' for default value, int
    - scale: scale factor, '0' for default value, float
    
    Output:
    Nothing is returned. Output image is automatically saved.
    
    Reference: http://orfeo-toolbox.org/CookBook/CookBooksu113.html#x144-9030004.9.6
    ###################################################################################################################
    ''' 
    
    Segmentation = otbApplication.Registry.CreateApplication("Segmentation")
    Segmentation.SetParameterString("in", input_img)
    Segmentation.SetParameterString("mode",output_mode)
    Segmentation.SetParameterString("mode."+output_mode+".out", output_file)
    Segmentation.SetParameterString("filter","edison")
    if (spatial_radius!=0):
        Segmentation.SetParameterInt("filter.edison.spatialr",spatial_radius)
    if (range_radius!=0):
        Segmentation.SetParameterFloat("filter.edison.ranger",range_radius)
    if (min_size!=0):
        Segmentation.SetParameterInt("filter.edison.minsize",min_size)
    if (scale!=0):
        Segmentation.SetParameterFloat("filter.edison.scale",scale)

    Segmentation.ExecuteAndWriteOutput()
    
    
def mprofiles_otb(input_img,output_file,output_mode,size,start,step,sigma):
    
    '''
    ###################################################################################################################
    Performs the edison-meanshift segmentation using OTB library
    
    Input:
    - input_image: path to the input image
    - output_file: path and name of the output file (raster or vector)
    - output_mode: 'raster' or 'vector' as a string
    - size: profile size, '0' for default value, int
    - start: initial radius, '0' for default value, int
    - step: radius step, '0' for default value, int
    - sigma: threshold of the final decision rule, '0' for default value, float
    
    Output:
    Nothing is returned. Output image is automatically saved.
    
    Reference: http://orfeo-toolbox.org/CookBook/CookBooksu113.html#x144-9030004.9.6
    ###################################################################################################################
    ''' 
    
    Segmentation = otbApplication.Registry.CreateApplication("Segmentation")
    Segmentation.SetParameterString("in", input_img)
    Segmentation.SetParameterString("mode",output_mode)
    Segmentation.SetParameterString("mode."+output_mode+".out", output_file)
    Segmentation.SetParameterString("filter","mprofiles")
    if (size!=0):
        Segmentation.SetParameterInt("filter.mprofiles.size",size)
    if (start!=0):
        Segmentation.SetParameterInt("filter.mprofiles.start",start)
    if (step!=0):
        Segmentation.SetParameterInt("filter.mprofiles.step",step)
    if (sigma!=0):
        Segmentation.SetParameterFloat("filter.mprofiles.sigma",sigma)

    Segmentation.ExecuteAndWriteOutput()
    

def Shp2Rast(input_shape,output_image,rows,cols,field_name):
    
    '''
    ###################################################################################################################
    Conversion from ESRI shapefile to raster
    
    Input:
    - input_shape: path of the input shapefile
    - output_image: path and name of the output raster file
    - rows: rows of the output raster
    - cols: columns of the output raster
    - field_name: name of the field from the shapefile used to differenciate segments (for example DN)
    
    Output:
    Nothing is returned. Output image is automatically saved.
    ###################################################################################################################
    ''' 
    
    driver_shape=osgeo.ogr.GetDriverByName('ESRI Shapefile')
    data_source = driver_shape.Open(input_shape)
    source_layer = data_source.GetLayer()
    source_srs = source_layer.GetSpatialRef()
    x_min, x_max, y_min, y_max = source_layer.GetExtent()
    
    pixel_size_x = float((x_max-x_min)) / float(cols)
    pixel_size_y = float((y_max-y_min)) / float(rows)
    target_ds = osgeo.gdal.GetDriverByName('GTiff').Create(output_image, cols,rows, 1, GDT_Float32)
    target_ds.SetGeoTransform((x_min, pixel_size_x, 0,y_max, 0, -pixel_size_y,))
    if source_srs:
        # Make the target raster have the same projection as the source
        target_ds.SetProjection(source_srs.ExportToWkt())
    else:
        # Source has no projection (needs GDAL >= 1.7.0 to work)
        target_ds.SetProjection('LOCAL_CS["arbitrary"]')
    
    # Rasterize
    err = osgeo.gdal.RasterizeLayer(target_ds,[1], source_layer,burn_values=[0],options=["ATTRIBUTE="+field_name])
    if err != 0:
        raise Exception("error rasterizing layer: %s" % err)
 
    
def Rast2Shp(input_image,output_shape):
    
    '''
    ###################################################################################################################
    Conversion from raster to ESRI shapefile
    
    Input:
    - input_image: path of the input raster
    - output_shape: path and name of the output shapefile
    
    Output:
    Nothing is returned. Output shapefile is automatically saved.
    ###################################################################################################################
    ''' 
    
    src_image = osgeo.gdal.Open(input_image)
    src_band = src_image.GetRasterBand(1)
    projection = src_image.GetProjection()
    
    driver_shape=osgeo.ogr.GetDriverByName('ESRI Shapefile')
    outfile=driver_shape.CreateDataSource(output_shape)
    outlayer=outfile.CreateLayer('Conversion',geom_type=osgeo.ogr.wkbPolygon)
    dn = osgeo.ogr.FieldDefn('DN',osgeo.ogr.OFTInteger)
    outlayer.CreateField(dn)
    
    #Polygonize
    osgeo.gdal.Polygonize(src_band,None,outlayer,0)
    
    outprj=osgeo.osr.SpatialReference(projection)
    outprj.MorphToESRI()
    file_prj = open(output_shape[:-4]+'.prj', 'w')
    file_prj.write(outprj.ExportToWkt())
    file_prj.close()
    