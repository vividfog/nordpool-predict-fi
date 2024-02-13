from selenium import webdriver
from selenium.webdriver.common.by import By

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

# Save all SVG elements found to separate files
for i, svg_element in enumerate(svg_elements):
    svg_content = svg_element.get_attribute('outerHTML')
    if "svgContainer" in svg_content:
        with open(f"output_{i}.svg", "w") as file:
                file.write(svg_content)

# Close the driver
driver.quit()
