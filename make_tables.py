import sqlite3

# Connect to the SQLite database
conn = sqlite3.connect("cache/prediction.db")
# Create a cursor object
c = conn.cursor()
# Add "Price [c/kWh]" column to the existing table
c.execute('''
    ALTER TABLE prediction
    ADD COLUMN "Price [c/kWh]" REAL
''')
# Commit the changes and close the connection
conn.commit()
conn.close()

