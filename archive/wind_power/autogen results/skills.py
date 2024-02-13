

##### Begin of find_papers_arxiv #####

import os
import re
import json
import hashlib


def search_arxiv(query, max_results=10):
    """
    Searches arXiv for the given query using the arXiv API, then returns the search results. This is a helper function. In most cases, callers will want to use 'find_relevant_papers( query, max_results )' instead.

    Args:
        query (str): The search query.
        max_results (int, optional): The maximum number of search results to return. Defaults to 10.

    Returns:
        jresults (list): A list of dictionaries. Each dictionary contains fields such as 'title', 'authors', 'summary', and 'pdf_url'

    Example:
        >>> results = search_arxiv("attention is all you need")
        >>> print(results)
    """

    import arxiv

    key = hashlib.md5(("search_arxiv(" + str(max_results) + ")" + query).encode("utf-8")).hexdigest()
    # Create the cache if it doesn't exist
    cache_dir = ".cache"
    if not os.path.isdir(cache_dir):
        os.mkdir(cache_dir)

    fname = os.path.join(cache_dir, key + ".cache")

    # Cache hit
    if os.path.isfile(fname):
        fh = open(fname, "r", encoding="utf-8")
        data = json.loads(fh.read())
        fh.close()
        return data

    # Normalize the query, removing operator keywords
    query = re.sub(r"[^\s\w]", " ", query.lower())
    query = re.sub(r"\s(and|or|not)\s", " ", " " + query + " ")
    query = re.sub(r"[^\s\w]", " ", query.lower())
    query = re.sub(r"\s+", " ", query).strip()

    search = arxiv.Search(query=query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance)

    jresults = list()
    for result in search.results():
        r = dict()
        r["entry_id"] = result.entry_id
        r["updated"] = str(result.updated)
        r["published"] = str(result.published)
        r["title"] = result.title
        r["authors"] = [str(a) for a in result.authors]
        r["summary"] = result.summary
        r["comment"] = result.comment
        r["journal_ref"] = result.journal_ref
        r["doi"] = result.doi
        r["primary_category"] = result.primary_category
        r["categories"] = result.categories
        r["links"] = [str(link) for link in result.links]
        r["pdf_url"] = result.pdf_url
        jresults.append(r)

    if len(jresults) > max_results:
        jresults = jresults[0:max_results]

    # Save to cache
    fh = open(fname, "w")
    fh.write(json.dumps(jresults))
    fh.close()
    return jresults


#### End of find_papers_arxiv ####

        

##### Begin of generate_images #####

from typing import List
import uuid
import requests  # to perform HTTP requests
from pathlib import Path

from openai import OpenAI


def generate_and_save_images(query: str, image_size: str = "1024x1024") -> List[str]:
    """
    Function to paint, draw or illustrate images based on the users query or request. Generates images from a given query using OpenAI's DALL-E model and saves them to disk.  Use the code below anytime there is a request to create an image.

    :param query: A natural language description of the image to be generated.
    :param image_size: The size of the image to be generated. (default is "1024x1024")
    :return: A list of filenames for the saved images.
    """

    client = OpenAI()  # Initialize the OpenAI client
    response = client.images.generate(model="dall-e-3", prompt=query, n=1, size=image_size)  # Generate images

    # List to store the file names of saved images
    saved_files = []

    # Check if the response is successful
    if response.data:
        for image_data in response.data:
            # Generate a random UUID as the file name
            file_name = str(uuid.uuid4()) + ".png"  # Assuming the image is a PNG
            file_path = Path(file_name)

            img_url = image_data.url
            img_response = requests.get(img_url)
            if img_response.status_code == 200:
                # Write the binary content to a file
                with open(file_path, "wb") as img_file:
                    img_file.write(img_response.content)
                    print(f"Image saved to {file_path}")
                    saved_files.append(str(file_path))
            else:
                print(f"Failed to download the image from {img_url}")
    else:
        print("No image data found in the response!")

    # Return the list of saved files
    return saved_files


# Example usage of the function:
# generate_and_save_images("A cute baby sea otter")


#### End of generate_images ####

        