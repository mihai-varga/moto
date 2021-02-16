import api_key
import argparse
import os
import shutil
import googlemaps
from pyproj import Geod
import gpxpy
import gpxpy.gpx

MAX_POINTS = 100
GUIDING_POINTS = 3
MAX_DIST_BETWEEN_POINTS = 290

STRIP_MODE = 'strip'
SNAP_TO_ROAD_MODE = 'snap_to_road'
STRIP_AND_SNAP = 'strip_and_snap'
STRIPPED_DIR_SUFFIX = "_stripped"
SNAPPED_DIR_SUFFIX = "_snapped"

# Removes waypoints and routes
def strip(gpx):
    del gpx.waypoints[:]
    del gpx.routes[:]

# Interpolates between points where the distance is > MAX_DIST_BETWEEN_POINTS
def interpolate(points):
    geoid = Geod(ellps="WGS84")
    new_points = []
    for lat, lon in points:
        if len(new_points) == 0:
            new_points.append((lat, lon))
        else:
            prev_lat, prev_lon = new_points[-1]
            dist = gpxpy.geo.haversine_distance(lat, lon, prev_lat, prev_lon)
            if dist >= MAX_DIST_BETWEEN_POINTS:
                extra_points = geoid.npts(prev_lon, prev_lat, lon, lat, dist / MAX_DIST_BETWEEN_POINTS)
                # Reverse order
                for new_lon, new_lat in extra_points:
                    new_points.append((new_lat, new_lon))
            new_points.append((lat, lon))
    return new_points

# Snaps points to roads
def snap_to_road(gpx):
    gmaps = googlemaps.Client(key=api_key.GOOGLE_MAPS_API_KEY)
    for track in gpx.tracks:
        for segment in track.segments:
            points = [(point.latitude, point.longitude) for point in segment.points]
            points = interpolate(points)
            segment_len = MAX_POINTS - GUIDING_POINTS
            segmented_paths = [points[i:i+segment_len] for i in xrange(0, len(points), segment_len)]

            snapped_points = []
            for path in segmented_paths:
                points = snapped_points[-GUIDING_POINTS:]
                points += path

                result = gmaps.snap_to_roads(points, interpolate=True)
                snapped_points += [(p['location']['latitude'], p['location']['longitude']) for p in result]

            segment.points = [gpxpy.gpx.GPXTrackPoint(latitude, longitude) for latitude, longitude in snapped_points]


def update_master_gpx(master_gpx, new_gpxs):
    for gpx in new_gpxs:
        strip(gpx)
        snap_to_road(gpx)

    master_track = master_gpx.tracks[0]
    for gpx in new_gpxs:
        for track in gpx.tracks:
            master_track.segments += track.segments


def read_gpx(file_name):
    with open(file_name, 'r') as f:
        return gpxpy.parse(f)


def read_gpxs(dir_name):
    gpxs = []
    for file_name in os.listdir(dir_name):
        gpxs.append(read_gpx(os.path.join(dir_name, file_name)))
    return gpxs


def write_gpx(file_name, gpx):
    with open(file_name, 'w') as f:
        f.write(gpx.to_xml())


def main():
    parser = argparse.ArgumentParser(description='Process a directory of GPX files and appends them to the master file.')
    parser.add_argument("master_gpx", help='Master file')
    parser.add_argument("input_dir", help='Input directory')
    args = parser.parse_args()

    master_gpx = read_gpx(args.master_gpx)
    new_gpxs = read_gpxs(args.input_dir)

    update_master_gpx(master_gpx, new_gpxs)

    write_gpx(args.master_gpx, master_gpx)

if __name__ == "__main__":
    main()
