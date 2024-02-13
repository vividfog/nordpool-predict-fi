import json
import re
from scipy.interpolate import interp1d
import numpy as np

# Load the JSON data from the uploaded file
with open('extracted_paths.json', 'r') as file:
    paths_data = json.load(file)

# This function will parse the SVG path for the "C" bezier curve command and return the points
def parse_bezier_path(path_d):
    # Match all instances of cubic bezier curves, which start with 'C'
    bezier_matches = re.findall(r'C[0-9\.,\s]+', path_d)
    bezier_points = []

    for match in bezier_matches:
        # Extract the numbers from the match
        points = re.findall(r'(\d+\.?\d*)', match)
        # Convert strings to floats and make them into tuples of (x,y)
        points = [float(p) for p in points]
        bezier_points.extend(list(zip(points[::2], points[1::2])))
        
    return bezier_points

# Define the scaling function for y-values
def scale_y(y, height, max_power):
    # Invert the y coordinate since SVG's y=0 is at the top
    y_inverted = height - y +60
    # Scale according to the SVG height and the range of power values
    megawatts = y_inverted / height * max_power
    return round(megawatts)

# SVG canvas size
svg_width = 2390
svg_height = 300
# Power range
max_power = 7000

# Extract the paths for the two bezier curves
bezier_paths = paths_data['paths']
scaled_data = []

# Process each path
for path in bezier_paths:
    # Parse the bezier path to extract the points
    bezier_points = parse_bezier_path(path)
    # Initialize a list to hold scaled y-values
    scaled_y_values = []

    # Scale y-values of the points
    for _, y in bezier_points:
            scaled_y = scale_y(y, svg_height, max_power)
            scaled_y_values.append(scaled_y)

    scaled_data.append(scaled_y_values)

# Write the scaled data to separate JSON files
output_files = []

for i, data in enumerate(scaled_data):
    if data != []:
        output_filename = f'scaled_bezier_path_{i+1}.json'
        with open(output_filename, 'w') as outfile:
            json.dump(data, outfile)
        output_files.append(output_filename)

output_files

