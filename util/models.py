import sqlite3
import json
import os
from datetime import datetime
from rich import print

# Database file path
DB_FILE = 'model/models.db'

def create_connection(db_file):
    """Create a database connection to the SQLite database specified by db_file"""
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except sqlite3.Error as e:
        print(e)
    return None

def write_model_stats(training_timestamp, MAE, MSE, R2, samples_MAE, samples_MSE, samples_R2, model_path):
    """
    Write the training statistics of the model to the database.
    """
    conn = create_connection(DB_FILE)
    with conn:
        sql = ''' INSERT INTO models(training_timestamp, MAE, MSE, R2, samples_MAE, samples_MSE, samples_R2, model_path)
                  VALUES(?,?,?,?,?,?,?,?) '''
        cur = conn.cursor()
        cur.execute(sql, (training_timestamp, MAE, MSE, R2, samples_MAE, samples_MSE, samples_R2, model_path))
        conn.commit()
        return cur.lastrowid

def read_model_stats():
    """
    Read all the model training statistics from the database.
    """
    conn = create_connection(DB_FILE)
    with conn:
        cur = conn.cursor()
        query = "SELECT * FROM models"
        cur.execute(query)
        rows = cur.fetchall()
        columns = [column[0] for column in cur.description]
        return [dict(zip(columns, row)) for row in rows]

def stats_json(folder_path):
    """
    Save the model training statistics to a JSON file named model_stats.json in the specified folder.
    """
    stats = read_model_stats()
    file_path = os.path.join(folder_path, 'model_stats.json')
    with open(file_path, 'w') as json_file:
        json.dump(stats, json_file, indent=4, default=str)

def stats(timestamp):
    """
    Retrieve the training statistics for a specific model identified by its model_path.
    """
    conn = create_connection(DB_FILE)
    with conn:
        cur = conn.cursor()
        query = "SELECT * FROM models WHERE training_timestamp = ?"
        cur.execute(query, (timestamp,))
        row = cur.fetchone()
        if row:
            columns = [column[0] for column in cur.description]
            return dict(zip(columns, row))
        else:
            return None

def list_models():
    """
    Retrieve all model training timestamps from the database.
    """
    conn = create_connection(DB_FILE)
    with conn:
        cur = conn.cursor()
        query = "SELECT training_timestamp FROM models ORDER BY training_timestamp DESC"
        cur.execute(query)
        rows = cur.fetchall()
        return [row[0] for row in rows]

# Example usage
if __name__ == "__main__":

    # Example of writing model stats
    # Ensure to replace the below example values with your actual model's training results
    # training_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
    # write_model_stats(training_timestamp, 1.5, 2.3, 0.9, 1.2, 2.1, 0.95, "model/example_model.joblib")
    
    # Example of listing all model timestamps
    # print("All model timestamps:")
    # for timestamp in list_models():
    #     print(timestamp)
    
    # Example of retrieving stats for a specific model
    # model_path = "model/example_model.joblib"
    # print(f"Stats for {model_path}:", stats(model_path))
    
    # Example of saving stats to JSON
    # stats_json('path_to_your_folder')  # Ensure the folder exists

    print("This feature is meant to be used as a module. It is not meant to be run as a standalone script.")
    exit(0)
