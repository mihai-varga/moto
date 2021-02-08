import api_key
import argparse
import os
import shutil
import googlemaps
from pyproj import Geod
import gpxpy
import gpxpy.gpx

MAX_POINTS = 100
GUIDING_POINTS = 10
MAX_ALLOWED_DISTANCE = 290

STRIP_MODE = 'strip'
SNAP_TO_ROAD_MODE = 'snap_to_road'
STRIP_AND_SNAP = 'strip_and_snap'
STRIPPED_DIR_SUFFIX = "_stripped"
SNAPPED_DIR_SUFFIX = "_snapped"

# Removes waypoints and routes
def strip(gpx):
    del gpx.waypoints[:]
    del gpx.routes[:]
    return gpx

# Interpolates between points where the distance is > MAX_ALLOWED_DISTANCE
def interpolate(points):
    geoid = Geod(ellps="WGS84")
    new_points = []
    for lat, lon in points:
        if len(new_points) == 0:
            new_points.append((lat, lon))
        else:
            prev_lat, prev_lon = new_points[-1]
            dist = gpxpy.geo.haversine_distance(lat, lon, prev_lat, prev_lon)
            if dist >= MAX_ALLOWED_DISTANCE:
                extra_points = geoid.npts(prev_lon, prev_lat, lon, lat, dist / MAX_ALLOWED_DISTANCE)
                print 'extra points = ', extra_points
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
    return gpx

def process_files(input_dir, output_dir, func):
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.mkdir(output_dir)
    for file_name in os.listdir(input_dir):
        with open(os.path.join(input_dir, file_name), 'r') as f_in:
            gpx = gpxpy.parse(f_in)
            result = func(gpx)
            with open(os.path.join(output_dir, file_name), 'w') as f_out:
                f_out.write(result.to_xml())

def main():
    parser = argparse.ArgumentParser(description='Process a directory of GPX files.')
    parser.add_argument("input_dir", help='Input directory')
    parser.add_argument("mode", choices=[STRIP_MODE, SNAP_TO_ROAD_MODE, STRIP_AND_SNAP])
    args = parser.parse_args()

    if args.mode == STRIP_MODE or args.mode == STRIP_AND_SNAP:
        process_files(args.input_dir, args.input_dir + STRIPPED_DIR_SUFFIX, strip)

    if args.mode == SNAP_TO_ROAD_MODE or args.mode == STRIP_AND_SNAP:
        input_dir = args.input_dir
        if args.mode == STRIP_AND_SNAP:
            input_dir += STRIPPED_DIR_SUFFIX
        process_files(input_dir, args.input_dir + SNAPPED_DIR_SUFFIX, snap_to_road)

if __name__ == "__main__":
    main()
