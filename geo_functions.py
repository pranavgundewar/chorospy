import os
from osgeo import ogr, osr, gdal
import pandas
import random
import math
import numpy

#########################################
# funtion to produce polygons from points
# inPoints is a list of lists e.g. [[[x1,y1], [x2,y2]], [[x3,y3], [x4,y4]]]
# each list of points is saved as a seperate feauture in the final vector file
#########################################
def pointToGeo(inProj, inPoints, outFile, buffer = False, bufferZone = 10000, convexHull = False, outFormat = 'json'):
    #define projections for the transformation
    inSpatialRef = osr.SpatialReference()
    inSpatialRef.ImportFromEPSG(inProj)
    #the points will be temporarily converted to web mercator that uses meters for units (the buffer is expressed in meters)
    outSpatialRef = osr.SpatialReference()
    outSpatialRef.ImportFromEPSG(3857) #Web Mercator
    coordTransform = osr.CoordinateTransformation(inSpatialRef, outSpatialRef)

    #hierarchy of geo file creation: Driver -> Datasource -> Layer -> Feature -> Geometry ->Polygone
    if outFormat == 'json':
        driver = ogr.GetDriverByName('GeoJSON')
    elif outFormat == 'shp':
        driver = ogr.GetDriverByName('ESRI Shapefile')

    outShape = '{}.{}'.format(outFile, outFormat)

    if os.path.exists(outShape):
        driver.DeleteDataSource(outShape)
    shapeData = driver.CreateDataSource(outShape)

    #Create layer
    layer = shapeData.CreateLayer('clipExtent', inSpatialRef, ogr.wkbMultiPolygon)
    layerDefinition = layer.GetLayerDefn()


    for i, feat in enumerate(inPoints):
        # create feature
        featureIndex = i
        feature = ogr.Feature(layerDefinition)
        # create geometries
        if buffer == True:
            #create multipolygone to store buffer zones
            multiPoly = ogr.Geometry(ogr.wkbMultiPolygon)
            for point in feat:
                gps_point = ogr.Geometry(ogr.wkbPoint)
                gps_point.AddPoint(point[0],point[1])
                gps_point.Transform(coordTransform)
                buffPoint = gps_point.Buffer(bufferZone)
                multiPoly.AddGeometry(buffPoint)
            
            #join overlapping polygones
            multiPoly = multiPoly.UnionCascaded()
            
            if convexHull == True:
                # Calculate convex hull
                multiPoly = multiPoly.ConvexHull()

            #reproject back to WGS84
            FinTransform = osr.CoordinateTransformation(outSpatialRef, inSpatialRef)
            multiPoly.Transform(FinTransform)
            # geometry in feature
            feature.SetGeometry(multiPoly)
            feature.SetFID(featureIndex)
            # feature in layer
            layer.CreateFeature(feature)

        else: #simple polygones from points
                multiPoly = ogr.Geometry(ogr.wkbPolygon)
                ring = ogr.Geometry(ogr.wkbLinearRing)

                for point in feat:
                    gps_point = ogr.Geometry(ogr.wkbPoint)
                    gps_point.AddPoint(point[0],point[1])
                    ring.AddPoint(gps_point.GetX(), gps_point.GetY())

                multiPoly.AddGeometry(ring)
                # geometry in feature
                feature.SetGeometry(multiPoly)
                feature.SetFID(featureIndex)
                # feature in layer
                layer.CreateFeature(feature)

        #Clean
        multiPoly.Destroy()
        feature.Destroy()
        shapeData.Destroy()
        
    print('Geometry file created!')
        
#function for disaggregating occurence points
# dist in degrees
# 100m = 0.001189387868; for 1km = 0.008333333333333; for 10km = 0.08333333333333
def disaggregate(df, Lon, Lat, dist): 
    train = df.drop_duplicates() #drop dublicates
    finalDF = pandas.DataFrame(columns=[Lon, Lat])
    removedDF = pandas.DataFrame(columns=[Lon, Lat])
    kept = 0
    excl = 0
    
    while len(train) > 1:
        points = len(train)
        #pick a random point in the dataset
        i = random.randrange(0, points, 1)
        #calculate euclidean distance between the random point and all other points (including itself)
        eucl = ((train[Lon] - train[Lon].iloc[i])**2 + (train[Lat] - train[Lat].iloc[i])**2).apply(math.sqrt) 
        #if there exists points with smaller distance, exclude point
        if eucl[eucl <= dist].count() > 1:
            excl+=1
            exclRow = train.loc[i, [Lon,Lat]]
            removedDF = removedDF.append(exclRow, ignore_index=True)
        else:
            kept+=1
            keptRow = train.loc[i, [Lon,Lat]]
            finalDF = finalDF.append(keptRow, ignore_index=True)


        train = train.drop(train.index[i]).reset_index(drop=True)
        
    print('Occurences removed: %s, Occurences kept: %s' %(excl, kept))
    return(finalDF, removedDF)


def getValuesAtPoint(indir, rasterfileList, pos):
    #gt(2) and gt(4) coefficients are zero, and the gt(1) is pixel width, and gt(5) is pixel height.
    #The (gt(0),gt(3)) position is the top left corner of the top left pixel of the raster.
    for i, rs in enumerate(rasterfileList):
        
        presValues = []
        gdata = gdal.Open('{}/{}.tif'.format(indir,rs))
        gt = gdata.GetGeoTransform()

        x0, y0 , w , h = gt[0], gt[3], gt[1], gt[5]

        data = gdata.ReadAsArray().astype(numpy.float)
        #free memory
        gdata = None
        
        if i == 0:
            #iterate through the points
            for p in pos.iterrows():
                x = int((p[1]['x'] - x0)/w)
                Xc = x0 + x*w + w/2 #the cell center x
                y = int((p[1]['y'] - y0)/h)
                Yc = y0 + y*h + h/2 #the cell center y
                try:
                    if data[y,x] != -9999.0:
                        presVAL = [p[1]['x'],p[1]['y'], '{:.6f}'.format(Xc), '{:.6f}'.format(Yc), data[y,x]]
                        presValues.append(presVAL)
                except:
                    pass
            df = pandas.DataFrame(presValues, columns=['x', 'y', 'Xc', 'Yc', rs])
        else:
            #iterate through the points
            for p in pos.iterrows():
                x = int((p[1]['x'] - x0)/w)
                y = int((p[1]['y'] - y0)/h)
                try:
                    if data[y,x] != -9999.0:
                        presValues.append(data[y,x])
                except:
                    pass
            df[rs] = pandas.Series(presValues)

    return df


#### function to get all coordinates and corresponding values of the raster pixels
def getRasterValues(indir, rasterfileList):
    
    for i, rs in enumerate(rasterfileList):
        
        if i == 0:
            vList = []
            gdata = gdal.Open('{}/{}.tif'.format(indir,rs))
            gt = gdata.GetGeoTransform()
            data = gdata.ReadAsArray().astype(numpy.float)
            #free memory
            gdata = None

            x0, y0 , w , h = gt[0], gt[3], gt[1], gt[5]

            for r, row in enumerate(data):
                x = 0
                for c, column in enumerate(row):
                    x = x0 + c*w + w/2
                    y = y0 + r*h + h/2

                    vList.append(['{:.6f}'.format(x),'{:.6f}'.format(y),column])
            df = pandas.DataFrame(vList, columns=['Xc', 'Yc', rs])
            
        else:
            gdata = gdal.Open('{}/{}.tif'.format(indir,rs))
            gt = gdata.GetGeoTransform()
            data = gdata.ReadAsArray().astype(numpy.float)
            #free memory
            gdata = None
            vList = [c for r in data for c in r]
            df[rs] = pandas.Series(vList)
            
    return(df)
 
# geo raster to numpy     
def raster2array(rasterfn):
    raster = gdal.Open(rasterfn)
    band = raster.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    array = band.ReadAsArray()
    
    geoTransform = raster.GetGeoTransform()
    minx = geoTransform[0]
    maxy = geoTransform[3]
    maxx = minx + geoTransform[1]*raster.RasterXSize
    miny = maxy + geoTransform[5]*raster.RasterYSize
    extent =  [minx, maxx, miny, maxy]
    del raster, band
    return array, nodata, extent

# numpy array to geo raster
def array2raster(newRaster, RefRaster,array, noData, datatype):
    #data type conversion
    NP2GDAL_CONVERSION = { "uint8": 1, "int8": 1, "uint16": 2, "int16": 3, 
                          "uint32": 4, "int32": 5, "float32": 6, "float64": 7,
                          "complex64": 10, "complex128": 11,
                         }
    
    rfRaster = gdal.Open(RefRaster)
    geotransform = rfRaster.GetGeoTransform()
    originX = geotransform[0]
    originY = geotransform[3]
    pixelWidth = geotransform[1]
    pixelHeight = geotransform[5]
    cols = array.shape[1]
    rows = array.shape[0]

    driver = gdal.GetDriverByName('GTiff')
    outRaster = driver.Create(newRaster, cols, rows,1, NP2GDAL_CONVERSION[datatype])
    outRaster.SetGeoTransform((originX, pixelWidth, 0, originY, 0, pixelHeight))
    outband = outRaster.GetRasterBand(1)
    outband.SetNoDataValue(noData)
    outband.WriteArray(array)
    outRasterSRS = osr.SpatialReference()
    outRasterSRS.ImportFromWkt(rfRaster.GetProjectionRef())
    outRaster.SetProjection(outRasterSRS.ExportToWkt())
    outband.FlushCache()
    del rfRaster