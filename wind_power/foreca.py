from selenium import webdriver
from selenium.webdriver.common.by import By
from xml.etree import ElementTree as ET
from xml.dom.minidom import parseString
from xml.etree import ElementTree as ET
import numpy as np
from datetime import datetime, timedelta
import pytz
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def beautify_svg_content(svg_content):
    """
    Beautify SVG content passed as a string and return the prettified string.
    """
    dom = parseString(svg_content)
    pretty_xml_as_string = dom.toprettyxml()
    return pretty_xml_as_string

# Set up Safari options
options = webdriver.SafariOptions()

# Set up driver
driver = webdriver.Safari(options=options)

# Open the web page
driver.get("https://www.foreca.fi/sahkon-hinta")

# Wait for JavaScript to execute (if needed)
driver.implicitly_wait(5)  # waits for 5 seconds

# Find the SVG elements that contain 'WindPowerMeteogram' in their class attribute
svg_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='WindPowerMeteogram']")

for i, svg_element in enumerate(svg_elements):
    svg_content = svg_element.get_attribute('outerHTML')
    if "svgContainer" in svg_content:
        # Use the updated function to beautify the SVG content
        beautified_svg_content = beautify_svg_content(svg_content)
        
        # Save the beautified SVG content to a file
        with open(f"foreca_{i}.html", "w") as file:
            file.write(beautified_svg_content)

for i, svg_element in enumerate(svg_elements):
    # Directly fetch the 'innerHTML' of the SVG element, which should exclude the <div> wrapper
    svg_content = svg_element.get_attribute('innerHTML')
    
    # Check if the content actually contains an <svg> element before proceeding
    if '<svg' in svg_content:
        # Directly proceed with beautifying the SVG content without needing to strip the <div> tags
        beautified_svg_content = beautify_svg_content(svg_content)
        
        # Save the beautified SVG content to a file with .svg extension
        with open(f"foreca_{i}.svg", "w") as file:
            file.write(beautified_svg_content)

# Close the driver
driver.quit()

# Load and parse the SVG file
svg_path = 'foreca_1.svg'
tree = ET.parse(svg_path)
root = tree.getroot()

# Helper function to parse and structure gridline data
def parse_gridlines(group):
    gridlines = []
    for path in group.findall('.//{http://www.w3.org/2000/svg}path'):
        d = path.get('d')
        gridlines.append(d)
    return gridlines

# Helper function to parse text elements (dates, days, hours)
def parse_texts(group):
    texts = []
    for text in group.findall('.//{http://www.w3.org/2000/svg}text'):
        x = text.get('x')
        content = text.text
        texts.append({'x': float(x), 'content': content})
    return texts

# Initialize containers for extracted information
vertical_minor_lines = []
vertical_major_lines = []
horizontal_lines = []
date_labels = []
hour_labels = []
date_texts = []

# Iterate through SVG groups to extract specific data based on attributes
for group in root.findall('.//{http://www.w3.org/2000/svg}g'):
    stroke = group.get('stroke')
    fill = group.get('fill')
    font_weight = group.get('font-weight')
    
    # Minor vertical gridlines
    if stroke == '#eeeeee' and group.get('stroke-width') == '1':
        vertical_minor_lines = parse_gridlines(group)
    
    # Major vertical gridlines (date boundaries)
    elif stroke == '#cdcdcd' and group.get('stroke-width') == '1':
        paths = group.findall('.//{http://www.w3.org/2000/svg}path')
        if paths[0].get('d').startswith('M') and 'V' in paths[0].get('d'):
            vertical_major_lines = parse_gridlines(group)
        else:  # Horizontal lines (MW forecasts)
            horizontal_lines = parse_gridlines(group)
    
    # Date names and Date texts
    elif fill == '#000' and font_weight == 'bold':
        date_labels = parse_texts(group)
    elif fill == '#000' and font_weight == 'regular':
        texts = parse_texts(group)
        if len(texts[0]['content']) == 5:  # Date in "DD.MM." format
            date_texts = texts
        else:  # Hour labels
            hour_labels = texts

print("Lines and lablews extracted from the SVG file")
print(len(vertical_minor_lines), len(vertical_major_lines), len(horizontal_lines), len(date_labels), len(hour_labels), len(date_texts))
print("Vertical Minor Lines:", vertical_minor_lines)  # Display the minor vertical gridlines to verify the result
print("Vertical Major Lines:", vertical_major_lines)  # Display the major vertical gridlines to verify the result
print("Horizontal Lines:", horizontal_lines)  # Display the horizontal gridlines to verify the result
print("Date Labels:", date_labels)  # Display the date labels to verify the result
print("Hour Labels:", hour_labels)  # Display the hour labels to verify the result
print("Date Texts:", date_texts)  # Display the date texts to verify the result

# Sort the hour labels by their X coordinates
hour_labels_sorted = sorted(hour_labels, key=lambda x: x['x'])

# Get today's year and month for year change detection
today = datetime.today()
current_year = today.year
current_month = today.month

# Function to adjust year based on month transition
def adjust_year_for_month_transition(month, current_month, current_year):
    if current_month == 12 and month == 1:
        return current_year + 1
    return current_year

# Function to pair hour labels with the closest preceding date text
def pair_dates_with_hours(date_texts, hour_labels, current_year, current_month):
    paired_datetime_x = []
    last_date = None

    # Sort date_texts by 'x' to ensure they are in the correct order
    date_texts = sorted(date_texts, key=lambda dt: dt['x'])
    
    for hour_label in hour_labels:
        hour_x = hour_label['x']
        # Find the most recent date text with 'x' less than or equal to hour_x
        for date_text in date_texts:
            if date_text['x'] <= hour_x:
                last_date = date_text
            else:
                break

        if last_date:
            # Parse the date and hour
            day, month = map(int, last_date['content'].split('.')[:2])
            year = adjust_year_for_month_transition(month, current_month, current_year)
            hour = int(hour_label['content'])
            
            # Create datetime object
            dt = datetime(year, month, day, hour)
            paired_datetime_x.append({'datetime': dt, 'x': hour_x})
    
    return paired_datetime_x

# Pair the hour labels with date texts to create datetime objects
paired_datetime_x = pair_dates_with_hours(date_texts, hour_labels, current_year, current_month)

for x in paired_datetime_x:
    print(f"DateTime: {x['datetime']}, X: {x['x']}")  # Display the paired datetime and X values to verify the result

def find_x_for_datetime(target_datetime, paired_datetime_x):
    # First, ensure the paired_datetime_x is sorted by datetime
    paired_datetime_x_sorted = sorted(paired_datetime_x, key=lambda x: x['datetime'])

    # Now, find the x value for the target datetime
    # If the target datetime is out of range, return None
    if target_datetime < paired_datetime_x_sorted[0]['datetime'] or \
       target_datetime > paired_datetime_x_sorted[-1]['datetime']:
        return None

    prev_entry = None
    for entry in paired_datetime_x_sorted:
        if entry['datetime'] == target_datetime:
            # Exact match found
            return entry['x']
        elif entry['datetime'] > target_datetime and prev_entry:
            # The target_datetime is between prev_entry and entry
            # Perform linear interpolation for the x value
            time_diff = entry['datetime'] - prev_entry['datetime']
            x_diff = entry['x'] - prev_entry['x']
            time_ratio = (target_datetime - prev_entry['datetime']) / time_diff
            interpolated_x = prev_entry['x'] + time_ratio * x_diff
            return interpolated_x
        prev_entry = entry
    
    # If no entries are found (which should not happen due to the range check), return None
    return None

# Example usage:
target_datetimes = datetime(2024, 2, 20, 13, 0), datetime(2024, 2, 15, 9, 0), datetime(2024, 2, 25, 2, 0)
for target_datetime in target_datetimes:
    x_value = find_x_for_datetime(target_datetime, paired_datetime_x)
    print(f"The X value for {target_datetime} is: {x_value}")

def interpolate_hours(hours):
    interpolated_hours = []
    index = 0  # Initialize a counter for the index
    for i in range(len(hours) - 1):
        current_hour = int(hours[i]['content'])
        next_hour = int(hours[i + 1]['content'])
        current_x = hours[i]['x']
        next_x = hours[i + 1]['x']
        
        # Calculate the gap in hours, considering the 24-hour wrap around
        hour_gap = (next_hour - current_hour) % 24
        if hour_gap > 1:
            # Calculate the spacing in X coordinates per hour
            x_increment = (next_x - current_x) / hour_gap
            for j in range(1, hour_gap):
                interpolated_hour = (current_hour + j) % 24
                interpolated_x = current_x + j * x_increment
                # Add an index to each interpolated hour
                interpolated_hours.append({'x': interpolated_x, 'content': f"{interpolated_hour:02d}", 'index': index})
                index += 1  # Increment the index
        # Add the original hour with its index
        interpolated_hours.append({**hours[i], 'index': index})
        index += 1  # Increment the index
    
    interpolated_hours.append({**hours[-1], 'index': index})  # Add the last hour with its index
    
    # Ensure the final list is sorted by X coordinate
    interpolated_hours_sorted = sorted(interpolated_hours, key=lambda x: x['x'])
    return interpolated_hours_sorted

# Perform interpolation
interpolated_hours = interpolate_hours(hour_labels_sorted)

print("Interpolated Hours:", interpolated_hours)  # Display the interpolated hours to verify the result
print("Length of Interpolated Hours:", len(interpolated_hours))  # Display the length to verify the result

# Function to extract Bezier paths and their starting points
def extract_bezier_paths(root):
    bezier_paths = []
    for path in root.findall('.//{http://www.w3.org/2000/svg}path'):
        d = path.get('d')
        stroke = path.get('stroke')
        # Only consider paths with a specified stroke color (to filter out gridlines)
        if stroke and 'C' in d:
            commands = d.split('C')  # Split at Bezier curve commands
            start_point = commands[0].replace('M', '').strip()  # Initial move command
            x_start, y_start = [float(n) for n in start_point.split(',')]
            bezier_paths.append({'x_start': x_start, 'y_start': y_start, 'd': d, 'stroke': stroke})
    return bezier_paths

# Extract Bezier paths from the SVG
bezier_paths = extract_bezier_paths(root)

# Display number of Bezier paths extracted and a sample for verification
#print("-------------------------------------------------------------------------------------------------------------")

#print(len(bezier_paths), bezier_paths[:1])  # Display a path to verify the extraction result

# Extract the first Bezier path from the SVG content
bezier_paths = []
for path in root.findall('.//{http://www.w3.org/2000/svg}path[@stroke]'):
    d = path.get('d')
    stroke = path.get('stroke')
    bezier_paths.append({'d': d, 'stroke': stroke})

# Focus on the first path
first_path_d = bezier_paths[0]['d']

# Correctly handle parsing of the Bezier path by focusing on segment divisions and mean Y calculation

# Extract segments correctly by considering 'M' start and subsequent 'C' segments
# The issue was with incorrectly handling the segment data; let's split and process it correctly
segments = first_path_d.split('C')
start_coords = segments[0][1:].split(',')
start_x, start_y = map(float, start_coords)

# Initialize the xy_matrix with the actual start point
xy_matrix = [{'x': start_x, 'y': start_y}]

# Process each 'C' segment to extract the end point
for segment in segments[1:]:
    coords = segment.split(',')
    end_x, end_y = map(float, coords[-2:])
    # Append the end point of each segment to the xy_matrix
    xy_matrix.append({'x': end_x, 'y': end_y})

# Ensure only unique X values are included for simplification
unique_xy_matrix = []
last_x = -1
for point in xy_matrix:
    if point['x'] != last_x:
        unique_xy_matrix.append(point)
        last_x = point['x']

print("-------------------------------------------------------------------------------------------------------------")

print("Length of unique X-Y matrix:", len(unique_xy_matrix))  # Display the length for verification
print("Unique X-Y matrix:", unique_xy_matrix)  # Display the unique X-Y matrix for verification

# Plot the unique X-Y matrix to visualize the Bezier path
# Extract X and Y values
# x_values = [point['x'] for point in unique_xy_matrix]
# y_values = [point['y'] for point in unique_xy_matrix]

# # Create the plot
# plt.figure(figsize=(10, 6))  # Optional: Specify figure size
# plt.plot(x_values, y_values, marker='o', linestyle='-', color='blue')  # Plot with line and markers

# # Add labels and title for clarity
# plt.xlabel('X Coordinate')
# plt.ylabel('Y Coordinate')
# plt.title('Visualization of Bezier Path from SVG')
# plt.grid(True)  # Optional: Show grid for better visualization

# # Optional: Annotate start and end points
# plt.annotate('Start', (x_values[0], y_values[0]), textcoords="offset points", xytext=(-10,-10), ha='center')
# plt.annotate('End', (x_values[-1], y_values[-1]), textcoords="offset points", xytext=(10,10), ha='center')

# # Show the plot
# plt.show()

def interpolate_y(x, unique_xy_matrix):
    # Ensure the unique_xy_matrix is sorted by x
    sorted_xy_matrix = sorted(unique_xy_matrix, key=lambda p: p['x'])

    # Check if x is out of bounds
    if x < sorted_xy_matrix[0]['x'] or x > sorted_xy_matrix[-1]['x']:
        return None  # or some error indication

    # Find the points between which x falls
    lower_point = None
    upper_point = None
    for point in sorted_xy_matrix:
        if point['x'] <= x:
            lower_point = point
        elif point['x'] > x and lower_point is not None:
            upper_point = point
            break

    # Interpolate y
    if lower_point and upper_point:
        x_range = upper_point['x'] - lower_point['x']
        y_range = upper_point['y'] - lower_point['y']
        x_ratio = (x - lower_point['x']) / x_range
        interpolated_y = lower_point['y'] + x_ratio * y_range
        return interpolated_y

    # If no upper_point is found, it means x is exactly at the last known point
    return lower_point['y'] if lower_point else None

# Example usage
# Let's find the y value for an x value of 1000 (which is within the range of x values in unique_xy_matrix)
x_value = 0, 100, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000
for x in x_value:
    y_value = interpolate_y(x, unique_xy_matrix)
    print(f"The interpolated Y value for X={x} is: {y_value}")

for line in horizontal_lines:
    print(f"Line: {line}") 

paired_datetime_x_y = []

for entry in paired_datetime_x:
    x_value = entry['x']
    y_value = interpolate_y(x_value, unique_xy_matrix)
    if y_value is not None:  # Only add if y_value could be interpolated
        paired_datetime_x_y.append({
            'datetime': entry['datetime'],
            'x': x_value,
            'y': y_value
        })

for entry in paired_datetime_x_y:
    print(f"DateTime: {entry['datetime']}, X: {entry['x']}, Y: {entry['y']}")  # Display the paired datetime, X, and Y values to verify the result
print("Total number of entries:", len(paired_datetime_x_y))  # Display the length to verify the result

# # Extract Time (datetime) and Y values from paired_datetime_x_y
# times = [entry['datetime'] for entry in paired_datetime_x_y]
# ys = [entry['y'] for entry in paired_datetime_x_y]

# # Create the plot
# plt.figure(figsize=(10, 6))  # Set the figure size
# plt.plot(times, ys, marker='o', linestyle='-', color='blue')  # Plot Time vs Y with line and markers

# # Format the datetime axis
# plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
# plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=24))  # Adjust the interval to display more or fewer dates on the x-axis
# plt.gcf().autofmt_xdate()  # Auto-rotate the dates to fit them better

# # Add labels and title
# plt.xlabel('Datetime')
# plt.ylabel('Y Value')
# plt.title('Time vs Y Value')

# # Show grid
# plt.grid(True)

# # Display the plot
# plt.show()

y_coords = [int(line.split('M')[1].split('H')[0].split(',')[1]) for line in horizontal_lines]
print("Y Coordinates:", y_coords)  # Display the Y coordinates to verify the result

# Calculate MW per pixel based on the first (top) and last (bottom) Y coordinates
max_value = y_coords[-1]  # Top line (7000 MW)
min_value = y_coords[0]  # Bottom line (0 MW)

print("Max MW Value Y axis equivalent:", max_value)  # Display the max value to verify the result
print("Min MW value Y axis equivalent:", min_value)  # Display the min value to verify the result

# Define the function to calculate MW from Y, as previously discussed
def calculate_mw_from_y(y, max_value, min_value, y_top, y_bottom):
    if y_top > y_bottom:
        y_top, y_bottom = y_bottom, y_top
        max_value, min_value = min_value, max_value
    mw = min_value + ((max_value - min_value) / (y_bottom - y_top)) * (y - y_top)
    return mw

# Define the Y coordinates for the top and bottom lines and their corresponding MW values
y_top = max_value     # Y coordinate for max MW value
y_bottom = min_value # Y coordinate for min MW value
max_value = 7000 # MW value at the top line
min_value = 0    # MW value at the bottom line

# Assuming paired_datetime_x_y is populated and contains datetime, x, and y values
# Update the paired_datetime_x_y list to include the MW value for each entry
for entry in paired_datetime_x_y:
    entry['MW'] = max_value-calculate_mw_from_y(entry['y'], max_value, min_value, y_top, y_bottom)
    
for entry in paired_datetime_x_y:
    print(f"DateTime: {entry['datetime']}, X: {entry['x']}, Y: {entry['y']}, MW: {entry['MW']}")  # Display the paired datetime, X, Y, and MW values to verify the result
    
# Extract datetime and MW values for plotting
datetimes = [entry['datetime'] for entry in paired_datetime_x_y]
mws = [entry['MW'] for entry in paired_datetime_x_y]

# # Create the plot
# plt.figure(figsize=(12, 6))  # Adjust the figure size as needed
# plt.plot(datetimes, mws, marker='o', linestyle='-', color='blue', label='MW over Time')

# # Format the datetime x-axis
# plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
# plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
# plt.gcf().autofmt_xdate()  # Auto-format the dates to improve readability

# # Add labels, title, and legend
# plt.xlabel('Datetime')
# plt.ylabel('MW')
# plt.title('MW Prediction over Time')
# plt.legend()

# # Add grid for better readability
# plt.grid(True)

# # Display the plot
# plt.show()

# Function to interpolate X and Y
def interpolate_missing_entries(start_datetime, end_datetime, existing_entries):
    # Generate a complete list of hourly timestamps
    total_hours = int((end_datetime - start_datetime).total_seconds() / 3600)
    all_timestamps = [start_datetime + timedelta(hours=i) for i in range(total_hours + 1)]
    
    # Prepare for interpolation
    existing_datetimes = [entry['datetime'] for entry in existing_entries]
    xs = np.array([entry['x'] for entry in existing_entries])
    ys = np.array([entry['y'] for entry in existing_entries])
    
    # Use numpy.interp for linear interpolation of X and Y
    interpolated_entries = []
    for timestamp in all_timestamps:
        if timestamp not in existing_datetimes:
            # Calculate index for interpolation
            idx = np.searchsorted(existing_datetimes, timestamp, side='left')
            
            if idx == 0 or idx == len(existing_datetimes):
                continue  # Cannot interpolate for start and end
            
            # Interpolate X and Y
            x_interp = np.interp((timestamp - start_datetime).total_seconds(),
                                 [(existing_datetimes[idx-1] - start_datetime).total_seconds(), (existing_datetimes[idx] - start_datetime).total_seconds()],
                                 [xs[idx-1], xs[idx]])
            
            y_interp = np.interp((timestamp - start_datetime).total_seconds(),
                                 [(existing_datetimes[idx-1] - start_datetime).total_seconds(), (existing_datetimes[idx] - start_datetime).total_seconds()],
                                 [ys[idx-1], ys[idx]])
            
            # Interpolate MW
            mw_interp = max_value - calculate_mw_from_y(y_interp, max_value, min_value, y_top, y_bottom)
            
            interpolated_entries.append({'datetime': timestamp, 'x': x_interp, 'y': y_interp, 'MW': mw_interp})
    
    # Merge and sort entries
    full_entries = existing_entries + interpolated_entries
    full_entries.sort(key=lambda entry: entry['datetime'])
    
    return full_entries

# Assuming you have y_top, y_bottom, max_value, and min_value defined as before

# Interpolate missing entries
start_datetime = paired_datetime_x_y[0]['datetime']
end_datetime = paired_datetime_x_y[-1]['datetime']
paired_datetime_x_y = interpolate_missing_entries(start_datetime, end_datetime, paired_datetime_x_y)

# Now, paired_datetime_x_y contains entries for every hour, including interpolated values

# Define Helsinki timezone
helsinki_tz = pytz.timezone('Europe/Helsinki')

# Convert paired_datetime_x_y to the required JSON format, adjusting for UTC time
json_output = []
for entry in paired_datetime_x_y:
    # Convert the datetime to Helsinki time, then to UTC
    helsinki_time = helsinki_tz.localize(entry['datetime'])
    utc_time = helsinki_time.astimezone(pytz.utc)
    
    # Add the entry to json_output
    json_output.append({
        "datetime": utc_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wind_prediction_MWh": entry['MW']
    })

# Specify the file path where you want to save the JSON data
file_path = 'foreca_wind_power_prediction.json'

# Write the JSON output to a file
with open(file_path, 'w') as json_file:
    json.dump(json_output, json_file, indent=4)

print("JSON data has been written to:", file_path)