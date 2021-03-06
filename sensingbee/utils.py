import pandas as pd
import numpy as np
import urllib.request
import json
import geopandas as gpd
import fiona
import shapely


def ingestion3(Sensors, variables, k=5, osmf=None, deprf=None ,freq='D'):
    idx = pd.IndexSlice
    sens_names = Sensors.data.index.get_level_values(1).unique()
    sens_times = Sensors.data.index.get_level_values(2).unique()
    zxcols = []
    for var in variables:
        [zxcols.append(var) for i in range(k)]
        [zxcols.append('d_{}'.format(var)) for i in range(k)]
    zx = pd.DataFrame(index=pd.MultiIndex.from_product([sens_names,sens_times],names=['Sensor Name','Timestamp']),
                      columns=zxcols)
    times_without_enough_samples = []
    for s in sens_names:
        si = Sensors.sensors.loc[s]
        for t in sens_times:
            for var in variables:
                sdf = Sensors.data.loc[idx[var,:,t]] # data of the var variable at  time t
                mdf = Sensors.sensors.loc[sdf.index.get_level_values(1).unique()] # sensors about them
                #
                dij = mdf['geometry'].apply(lambda x: si['geometry'].distance(x)).sort_values()
                dij = dij.loc[(dij.index!=si.name)]
                if len(dij)>=k:
                    dij = dij.nsmallest(k)
                else:
                    if t not in times_without_enough_samples:
                        print('Warning: Not enough sensors for ',t)
                        times_without_enough_samples.append(t)
                    continue
                dij = sdf.loc[idx[var,dij.index,t],:].join(dij, on="Sensor Name")
                zx.loc[idx[si.name,t],'d_{}'.format(var)] = dij['geometry'].values
                zx.loc[idx[si.name,t],var] = dij['Value'].values
    if freq == 'H':
        zx['hour'] = zx.index.get_level_values(1).hour
        zx['dow'] = zx.index.get_level_values(1).dayofweek
        zx['day'] = zx.index.get_level_values(1).day
    elif freq == 'D':
        zx['dow'] = zx.index.get_level_values(1).dayofweek
        zx['day'] = zx.index.get_level_values(1).day
        zx['week'] = zx.index.get_level_values(1).week
    if osmf is not None:
        zx = zx.reset_index(level=1).join(osmf).set_index('Timestamp', append=True)
    if deprf is not None:
        zx = zx.reset_index(level=1).join(deprf[['Index of Multiple Deprivation (IMD) Score',
                'Income Score (rate)',
                'Employment Score (rate)',
                'Education, Skills and Training Score',
                'Crime Score',
                'Barriers to Housing and Services Score',
                'Living Environment Score',
                'Total population: mid 2012 (excluding prisoners)',
                'Population aged 16-59: mid 2012 (excluding prisoners)']]).set_index('Timestamp', append=True)
    return zx, Sensors.data.drop(times_without_enough_samples, level='Timestamp')

def mesh_ingestion(Sensors, meshgrid, variables, timestamp):
    idx = pd.IndexSlice
    timestamp = pd.to_datetime(timestamp)
    zxcols = []
    for var in variables:
        [zxcols.append(var.split('.')[0]) for i in range(5)]
        [zxcols.append('d_{}'.format(var.split('.')[0])) for i in range(5)]
    zmesh = pd.DataFrame(index=meshgrid.index, columns=zxcols)
    def loop_var(i):
        values = []
        for var in variables:
            st = Sensors.data.loc[idx[var,:,timestamp]]
            closest = Sensors.sensors.loc[st.index.get_level_values(1),'geometry'].apply(lambda x: x.distance(i['geometry'])).nsmallest(5)
            closest = st.loc[idx[var,closest.index,timestamp],:].join(closest, on='Sensor Name')

            values += list(closest['Value'].values)
            values += list(closest['geometry'].values)
        zmesh.loc[i.name] = values
    meshgrid.apply(lambda x: loop_var(x), axis=1)

    zmesh['dow'] = timestamp.dayofweek
    zmesh['day'] = timestamp.day
    zmesh = zmesh.join(meshgrid[meshgrid.columns[~meshgrid.columns.isin(['lat','lon','geometry'])]])
    return zmesh

def pull_osm_objects(bbox, line_objs, point_objs):
    points_query_string = ''.join(["node[\"highway\"=\"{}\"]{};".format(i,bbox) for i in point_objs])
    osm_points = "[out:json][timeout:100];({});out+geom;".format(points_query_string)
    osm_points = json.loads(urllib.request.urlopen('http://overpass-api.de/api/interpreter?data='+osm_points).read())
    points = []
    for p in osm_points['elements']:
        elem = {}
        try:
            elem['geometry'] = shapely.geometry.Point([p['lon'],p['lat']])
        except:
            continue
        try:
            elem['highway'] = p['tags']['highway']
        except:
            elem['highway'] = ''
        points.append(elem)
    points = gpd.GeoDataFrame(points,crs={'init': 'epsg:4326'}).to_crs(fiona.crs.from_epsg(4326))
    #
    lines_query_string = ''.join(["way[\"highway\"=\"{}\"]{};".format(i,bbox) for i in line_objs])
    osm_lines = "[out:json][timeout:100];({});>;<;out+geom;".format(lines_query_string)
    osm_lines = json.loads(urllib.request.urlopen('http://overpass-api.de/api/interpreter?data='+osm_lines).read())
    lines = []
    for l in osm_lines['elements']:
        elem = {}
        try:
            elem['geometry'] = shapely.geometry.LineString([[i['lon'],i['lat']] for i in l['geometry']])
        except:
            continue
        try:
            elem['highway'] = l['tags']['highway']
        except:
            elem['highway'] = ''
        lines.append(elem)
    lines = gpd.GeoDataFrame(lines,crs={'init': 'epsg:4326'}).to_crs(fiona.crs.from_epsg(4326))
    return lines, points

def pull_depr_sensors(sensors):
    lsoa_path = '/home/adelsondias/Repos/newcastle/air-quality/shape/Lower_Layer_Super_Output_Areas_December_2011_Full_Extent__Boundaries_in_England_and_Wales/Lower_Layer_Super_Output_Areas_December_2011_Full_Extent__Boundaries_in_England_and_Wales.shp'
    city = gpd.read_file(lsoa_path)
    city = city[city['lsoa11nm'].str.contains('Newcastle upon Tyne')]
    city = city.to_crs(fiona.crs.from_epsg(4326))
    city.crs = {'init': 'epsg:4326', 'no_defs': True}
    df = pd.read_csv('/home/adelsondias/Downloads/deprivation.csv')
    df = df[df['Local Authority District name (2013)'].str.contains('Newcastle')]
    dep_df = df.set_index('LSOA name (2011)').join(city.set_index('lsoa11nm'))
    dep_df = dep_df.dropna()
    dep_df = gpd.GeoDataFrame(dep_df[['Index of Multiple Deprivation (IMD) Score',
                'Income Score (rate)',
                'Employment Score (rate)',
                'Education, Skills and Training Score',
                'Crime Score',
                'Barriers to Housing and Services Score',
                'Living Environment Score',
                'Total population: mid 2012 (excluding prisoners)',
                'Population aged 16-59: mid 2012 (excluding prisoners)',
                'lsoa11cd', 'lsoa11nmw','geometry']])
    dep_sensors = gpd.sjoin(sensors.sensors,dep_df,how='inner', op='intersects')
    return dep_sensors
