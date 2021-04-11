import api_key
import argparse
import os
import shutil
import googlemaps
from pyproj import Geod
import gpxpy
import gpxpy.gpx
import h3

MAX_POINTS = 100
GUIDING_POINTS = 3
MAX_POINTS_DIST_METERS = 290

H3_LEVEL = 13
SEGMENT_MIN_LEN_METERS = 30

MASTER_JS_FILE = 'master_coordinates.js'
MASTER_COORDS_VAR = 'masterCoordinates'
DIFF_JS_FILE = 'diff_coordinates.js'
ORIG_COORDS_VAR = 'originalCoordinates'
NEW_COORDS_VAR = 'newCoordinates'
DIFF_COORDS_VAR = 'diffCoordinates'

# Removes waypoints and routes
def strip(gpx):
    del gpx.waypoints[:]
    del gpx.routes[:]

# Interpolates between points where the distance is > MAX_POINTS_DIST_METERS
def interpolate(points):
    geoid = Geod(ellps="WGS84")
    new_points = []
    for lat, lon in points:
        if len(new_points) == 0:
            new_points.append((lat, lon))
        else:
            prev_lat, prev_lon = new_points[-1]
            dist = gpxpy.geo.haversine_distance(lat, lon, prev_lat, prev_lon)
            if dist >= MAX_POINTS_DIST_METERS:
                extra_points = geoid.npts(prev_lon, prev_lat, lon, lat, dist / MAX_POINTS_DIST_METERS)
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
            segmented_paths = [points[i:i+segment_len] for i in range(0, len(points), segment_len)]

            snapped_points = []
            for path in segmented_paths:
                points = snapped_points[-GUIDING_POINTS:]
                points += path

                result = gmaps.snap_to_roads(points, interpolate=True)
                snapped_points += [(p['location']['latitude'], p['location']['longitude']) for p in result]

            segment.points = [gpxpy.gpx.GPXTrackPoint(latitude, longitude) for latitude, longitude in snapped_points]


# Returns a new gpx
def remove_duplicate_segments(master_gpx, new_gpxs):
    diff_gpx = gpxpy.gpx.GPX()
    diff_track = gpxpy.gpx.GPXTrack()
    diff_gpx.tracks.append(diff_track)
    covered_points = set()

    def update_covered_points(segment):
        for point in segment.points:
            covered_points.add(h3.geo_to_h3(point.latitude, point.longitude, H3_LEVEL))

    for track in master_gpx.tracks:
        for segment in track.segments:
            update_covered_points(segment)

    for gpx in new_gpxs:
        for track in gpx.tracks:
            for segment in track.segments:
                i = len(segment.points)
                prev_point_covered = False
                new_segment = gpxpy.gpx.GPXTrackSegment()
                already_covered_segment = gpxpy.gpx.GPXTrackSegment()

                for point in segment.points:
                    point_id = h3.geo_to_h3(point.latitude, point.longitude, H3_LEVEL)
                    if point_id not in covered_points:
                        if already_covered_segment.length_2d() < SEGMENT_MIN_LEN_METERS:
                            # The covered segment is too small. Append it to the new_segment
                            new_segment.points += already_covered_segment.points
                        else:
                            # The covered segment was large, but a new not covered segment
                            # is starting. We clear the state.
                            if new_segment.length_2d() >= SEGMENT_MIN_LEN_METERS:
                                update_covered_points(new_segment)
                                diff_track.segments.append(new_segment)
                            new_segment = gpxpy.gpx.GPXTrackSegment()

                        new_segment.points.append(point)
                        already_covered_segment.points.clear()
                    else:
                        already_covered_segment.points.append(point)

                # Last points not processed in the for loop.
                if already_covered_segment.length_2d() < SEGMENT_MIN_LEN_METERS:
                    new_segment.points += already_covered_segment.points
                if new_segment.length_2d() >= SEGMENT_MIN_LEN_METERS:
                    update_covered_points(new_segment)
                    diff_track.segments.append(new_segment)
    return diff_gpx


def update_master_gpx(master_gpx, new_gpxs):
    for gpx in new_gpxs:
        strip(gpx)
        snap_to_road(gpx)

    diff_gpx = remove_duplicate_segments(master_gpx, new_gpxs)

    # For debugging
    orig_coords = build_js_coordinates(ORIG_COORDS_VAR, [master_gpx])
    new_coords = build_js_coordinates(NEW_COORDS_VAR, new_gpxs)
    diff_coords = build_js_coordinates(DIFF_COORDS_VAR, [diff_gpx])
    write_js(DIFF_JS_FILE, orig_coords + new_coords + diff_coords)

    # Update master files
    master_track = master_gpx.tracks[0]
    for track in diff_gpx.tracks:
        master_track.segments += track.segments

    updated_master_coords = build_js_coordinates(MASTER_COORDS_VAR, [master_gpx])
    write_js(MASTER_JS_FILE, updated_master_coords)


def build_js_coordinates(var_name, gpxs):
    js = 'const %s = [\n' % (var_name)
    for gpx in gpxs:
        for track in gpx.tracks:
            for segment in track.segments:
                points = ['{lat: %s, lng: %s}' % (p.latitude, p.longitude) for p in segment.points]
                js += '[%s],\n' % (', '.join(points))
    js += '];\n'
    return js


def write_js(file_name, content):
    with open(file_name, 'w') as f:
        f.write(content)

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
