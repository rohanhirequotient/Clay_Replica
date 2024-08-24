import os
import requests
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
import time
import json
import datetime
import pandas as pd
import warnings
from cryptography.utils import CryptographyDeprecationWarning

# Suppress specific warning
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)
from openai import OpenAI
from pymongo import MongoClient

client = OpenAI(api_key="openai_api_key")
#date must be in the format "YYYY-MM-DD"
date = datetime.datetime.now().strftime("%Y-%m-%d")
# Persistent context (using assistant's memory)
persistent_context = ""

def connect_to_mongodb(uri, database_name):
    """
    Connect to a MongoDB database.
    
    :param uri: MongoDB connection string.
    :param database_name: Name of the database to connect to.
    :return: Database object.
    """
    try:
        # Create a MongoClient to the running MongoDB instance
        dbclient = MongoClient(uri)

        # Connect to the specified database
        database = dbclient["HQ-Sourcing-dev-UAT"]

        # Print a success message
        print(f"Successfully connected to the database: {database_name}")
        
        return database
    except Exception as e:
        print(f"Error occurred while connecting to MongoDB: {e}")
        return None

mongo_url = "mongodb+srv://admin-uat:82fAgWWOqNkhoQeh@sourcing-dev.agdch.mongodb.net/"
database_name = "HQ-Sourcing-dev-UAT"
db = connect_to_mongodb(mongo_url, database_name)

# Function to perform Google Search using Custom Search API
def google_search(query, api_key, cse_id, num=10):
    try:
        service = build("customsearch", "v1", developerKey=api_key)
        res = service.cse().list(q=query, cx=cse_id, num=num).execute()
        if 'items' in res:
            return res['items']
        else:
            print("No items found in the search results.")
            return []
    except Exception as e:
        print(f"An error occurred during the Google search: {e}")
        return []

# Function to break down the task into sub-tasks using GPT
def break_down_task(user_query):
    system_prompt = f"""
    You are an AI assistant specialized in answering queries and generating sub queries. If you know the answer to the query based on your training data or asked to output specific information already present in the query, respond directly. If more information is needed, indicate that further research is required. Answer with respect to today's date which is {date}.
    """
    user_prompt = f'The user is asking about "{user_query}". Output must be a very short summary of your knowledge. If output can be in one or two lines, output one or two lines only, or if further research is needed please explicitly state that. Do Not output any extra information. The output must strictly be in plaintext format.'

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1000,
        temperature=0.4
    ).choices[0].message.content.strip()

    if "further research" not in response.lower():
        user_query = "Direct Answer: " + user_query
        return [user_query]  # If the assistant can answer directly, return the original query
    else:
        system_prompt = f"""
        You are an AI assistant that breaks down complex tasks into simpler, actionable sub-tasks. The user will provide a query, and you need to break it down into multiple tasks that can be executed individually. Just give very high level necessary tasks and Do NOT give redundant tasks like verification, confirmation, compiling, and so on. Even if the number of sub tasks is 1, it is fine. 
        Sub tasks must be one liners which we send for web search directly. Do not include unnecessary subtasks which require manual effort and those which are not asked for in the query. Just give the necessary ones. Do not do comparisons and third party check if not asked. If a previous sub task has the required information, do not add similar sub tasks.
        Ensure that the number of sub tasks is as low as possible and the tasks are actionable. To keep the number low, where possible, combine sub tasks that are similar in nature and can be handled at once. Strictly Do not include any unnecessary sub tasks such as finding official websites, verifying information as separate sub-tasks. These tasks will be handled in the next step.
        In cases where Linkedin Urls must be visited, give only one sub task. This sub task will scrape and summarize the Linkedin Url.
        Return just a numbered list of sub tasks.
        """

        user_prompt = f"Break down the following task: '{user_query}' into sub-tasks."

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1000,
            temperature=0.4
        ).choices[0].message.content.strip()

        # Assume the response is a list of sub-tasks
        print("Sub-Tasks:")
        print(response)
        return response.split("\n")  # Split by newlines to create a list of tasks
    
def linkedin_scraper(linkedin_url):
    candidate_collection = db["candidates"]
    candidate = candidate_collection.find_one({"profileUrl": linkedin_url})
    candidate_details = ""
    if candidate and 'name' in candidate and candidate['name']:
        name = candidate['name']
        candidate_details = candidate_details + "\n" + f"The name of the person is {name}."
    if candidate and 'location' in candidate and candidate['location']:
        location = candidate['location']
        candidate_details = candidate_details + "\n" + f"The location of the person is {location}."
    if candidate and 'description' in candidate and candidate['description']:
        description = candidate['description']
        candidate_details = candidate_details + "\n" + f"The description of the person is {description}."
    if candidate and 'title' in candidate and candidate['title']:
        title = candidate['title']
        candidate_details = candidate_details + "\n" + f"The title of the person is {title}."
    if candidate and 'experience' in candidate and candidate['experience']:
        experience = candidate['experience']
        candidate_details = candidate_details + "\n" + f"The experience of the person is {experience}."
    if candidate and 'education' in candidate and candidate['education']:
        education = candidate['education']
        candidate_details = candidate_details + "\n" + f"The education of the person is {education}."
    if candidate and 'skills' in candidate and candidate['skills']:
        skills = candidate['skills']
        candidate_details = candidate_details + "\n" + f"The skills of the person are {skills}."
    if candidate and 'certificates' in candidate and candidate['certificates']:
        certifications = candidate['certificates']
        candidate_details = candidate_details + "\n" + f"The certifications of the person are {certifications}."
    if candidate and 'email' in candidate and candidate['email']:
        email = candidate['email']
        candidate_details = candidate_details + "\n" + f"The email of the person is {email}."
    if candidate and 'extractedSkills' in candidate and candidate['extractedSkills']:
        extracted_skills = candidate['extractedSkills']
        candidate_details = candidate_details + "\n" + f"The extracted skills of the person are {extracted_skills}."
    
    print(f"LinkedIn Data: {candidate_details}")
    results = summarize_linkedin(candidate_details)
    return results
   
def agent_execute_sub_task(sub_task):
    global persistent_context  # Access the global persistent context

    system_prompt = f"""
    You are an AI agent responsible for determining the appropriate action for a given sub-task and executing it directly.
    You have access to the following functions:
    1. crunchbase(company_name, crunchbase_api_key): Strictly call this function to retrieve only revenue, funding, employee count, funding, description, IPO, acquirers, investments, location, founding date, industries, and categories for any company but not for any other details.
    2. generate_query(api_key, sub_task, context): Call this function to perform a web search and further analysis which cannot be obtained from crunchbase.
    3. linkedin_scraper(linkedin_url, linkedinapi_key): Call this function to scrape LinkedIn url of the person or company when query requires information from a LinkedIn url. Strictly call only if a linkedin url is present in the sub task
    If you have knowledge on the sub-task based on your training data, the context provided, or asked to output specific information already present in the query, you can directly respond with the answer without calling any function.
    Do Not call any function if the substring 'Direct Answer: ' is present in the sub-task.
    Based on the sub-task and current context, decide which action to take and execute the necessary function.
    """
    user_prompt = f"Sub-task: '{sub_task}'."
    
    if persistent_context != "":
        user_prompt = user_prompt + f"Context: '{persistent_context}'."

    user_prompt = user_prompt + "Determine and execute the appropriate action(s)."
    
    if persistent_context != "":
        user_prompt = user_prompt + "Use the context provided to send appropriate parameters."

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            functions=[
                {
                    "name": "crunchbase",
                    "description": "Retrieve any of: revenue, funding, employee count, funding, description, IPO, acquirers, investments, location, founding date, industries, and categories only for any company but not for any other company related details.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "array", "items": {"type": "string"}},
                            "crunchbase_api_key": {"type": "string"},
                            "sub_task": {"type": "string"}
                        },
                        "required": ["company_name", "crunchbase_api_key", "sub_task"]
                    }
                },
                {
                    "name": "generate_query",
                    "description": "Perform a Google search based on the query if information can't be got from Crunchbase.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "api_key": {"type": "string"},
                            "sub_task": {"type": "string"},
                            "context": {"type": "string"}
                        },
                        "required": ["api_key", "sub_task", "context"]
                    }
                },
                {
                    "name": "linkedin_scraper",
                    "description": "Scrape LinkedIn url of the person or company present in the query when query requires information from a LinkedIn url. Strictly call only if a linkedin url is present in the sub task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "linkedin_url": {"type": "string"}
                        },
                        "required": ["linkedin_url"]
                    }
                }
            ],
            function_call="auto",  # Let the model decide which function to call
            max_tokens=300,
            temperature=0.4
        )

        # Check if the response contains a function call
        choice = response.choices[0].message

        if choice.function_call:
            function_call = choice.function_call

            function_name = function_call.name
            arguments = json.loads(function_call.arguments)  # Parse the arguments into a dictionary

            if function_name == "crunchbase":
                result = crunchbase(arguments['company_name'], arguments['crunchbase_api_key'], sub_task)
            elif function_name == "generate_query":
                result = generate_query(**arguments)
            elif function_name == "linkedin_scraper":
                result = linkedin_scraper(arguments['linkedin_url'])

            print("Function Execution Result:")
            print(result)

            # Update the persistent context with the results of this sub-task
            update_context(sub_task, result)
            return result
        else:
            print("No function was called.")
            return choice.content

    except Exception as e:
        print(f"An error occurred: {e}")
        return f"Error: {str(e)}"
    
# Mock function to retrieve company details from Crunchbase
import requests
import re

# Replace with your Crunchbase API key
CRUNCHBASE_API_KEY = "33df45b8be15cdf42a04057bd71569d4"

def crunchbase_auto_complete(name):
    """Function to search for the organization using Crunchbase's autocomplete."""
    
    method = "GET"

    url = "https://api.crunchbase.com/api/v4/autocompletes"
    headers = {
        'accept': "application/json",
        'X-cb-user-key': CRUNCHBASE_API_KEY
    }
    params = {
        'query': name,
        'limit': 1,
        'collection_ids': 'organizations'
    }
    
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def parse_revenue_range(value):
    """Parse the revenue range from the given value."""
    pattern = r'r_(\d+)'
    match = re.search(pattern, value)
    
    if match:
        revenue = int(match.group(1))
        if revenue == 0:
            return "Less than $1M"
        elif revenue == 1000:
            return "$1M to $10M"
        elif revenue == 10000:
            return "$10M to $50M"
        elif revenue == 50000:
            return "$50M to $100M"
        elif revenue == 100000:
            return "$100M to $500M"
        elif revenue == 500000:
            return "$500M to $1B"
        elif revenue == 1000000:
            return "$1B to $10B"
        elif revenue == 10000000:
            return "$10B+"
    else:
        funds_raised_ranges = [
            "Less than $1M",
            "$1M to $10M",
            "$10M to $50M",
            "$50M to $100M",
            "$100M to $500M",
            "$500M to $1B",
            "$1B to $10B",
            "$10B+",
        ]
        if value in funds_raised_ranges:
            return value
    return None

def crunchbase(company_names, crunchbase_api_key, sub_task):
    print("Executing Crunchbase Function")
    crunchbase_api_key = CRUNCHBASE_API_KEY
    headers = {
        "X-Cb-User-Key": crunchbase_api_key,
        "accept": "application/json"
    }
    print(f"Company Names: {company_names}")
    results = []

    for name in company_names:
        # Step 1: Use autocomplete to find the correct organization
        autocomplete_data = crunchbase_auto_complete(name)
        entities = autocomplete_data.get('entities', [])
        entity_def_id = entities[0].get('identifier', {}).get('entity_def_id')
        if not entities:
            results.append({
                'company_name': name,
                'error': "No match found"
            })
            continue

        uuid_entity = entities[0].get('identifier', {}).get('uuid')
        print(f"UUID for {name}: {uuid_entity}")

        # Step 2: Fetch detailed organization data using the UUID
        if uuid_entity:
            crunchbase_collection = db["crunchbaseorganizations"]
            if crunchbase_collection.find_one({"uuid": uuid_entity}):  # Check if the data is already in the database
                print(f"Data for {name} already exists in the database.")
                organization_data_total = crunchbase_collection.find_one({"uuid": uuid_entity})
                # get the keys name, industries, city, country, continent, region, revenue_range, employee_range, funding_summary, total_funding_amount_usd, last_funding_date, last_equity_funding_type, last_funding_type if they exist
                organization_data = {}
                if "name" in organization_data_total:
                    organization_data["name"] = organization_data_total["name"]
                if "industries" in organization_data_total:
                    organization_data["industries"] = organization_data_total["industries"]
                if "city" in organization_data_total:
                    organization_data["city"] = organization_data_total["city"]
                if "country" in organization_data_total:
                    organization_data["country"] = organization_data_total["country"]
                if "continent" in organization_data_total:
                    organization_data["continent"] = organization_data_total["continent"]
                if "region" in organization_data_total:
                    organization_data["region"] = organization_data_total["region"]
                if "revenue_range" in organization_data_total:
                    organization_data["revenue_range"] = organization_data_total["revenue_range"]
                if "employee_range" in organization_data_total:
                    organization_data["employee_range"] = organization_data_total["employee_range"]
                if "funding_summary" in organization_data_total:
                    organization_data["funding_summary"] = organization_data_total["funding_summary"]
                if "total_funding_amount_usd" in organization_data_total:
                    organization_data["total_funding_amount_usd"] = organization_data_total["total_funding_amount_usd"]
                if "last_funding_date" in organization_data_total:
                    organization_data["last_funding_date"] = organization_data_total["last_funding_date"]
                if "last_equity_funding_type" in organization_data_total:
                    organization_data["last_equity_funding_type"] = organization_data_total["last_equity_funding_type"]
                if "last_funding_type" in organization_data_total:
                    organization_data["last_funding_type"] = organization_data_total["last_funding_type"]
                if "cards" in organization_data_total and "ipos" in organization_data_total["cards"]:
                    organization_data["ipos"] = organization_data_total["cards"]["ipos"]
                if "cards" in organization_data_total and "fields" in organization_data_total["cards"] and "founded_on" in organization_data_total["cards"]["fields"]:
                    organization_data["founded_on"] = organization_data_total["cards"]["fields"]["founded_on"]
                results.append({
                    'company_name': name,
                    'data': organization_data
                })
            else:
                organization_data = fetch_organization_data(uuid_entity, headers, entity_def_id)
                if organization_data:
                    parsed_data = extract_and_parse_data(organization_data)
                    results.append({
                        'company_name': name,
                        'data': parsed_data
                    })
                else:
                    results.append({
                        'company_name': name,
                        'error': "No data found"
                    })
        else:
            results.append({
                'company_name': name,
                'error': "No UUID found"
            })

    results_str = "\n\n".join([f"{result['company_name']}: {result.get('data', result.get('error', 'Error'))}" for result in results])
    return summarize_content(sub_task, results_str)

def crunchbaseorglookup(uuid, sub_task, cards):
    url = f"https://api.crunchbase.com/api/v4/entities/organizations/{uuid}"
    
    params = {}
    if cards["cards"]:
        params["card_ids"] = cards["cards"]

    headers = {
        "accept": "application/json",
        "X-Cb-User-Key": CRUNCHBASE_API_KEY
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.RequestException as error:
        print(f"Error fetching organization data for UUID {uuid}: {error}")
        return None

def crunchbaseinvestlookup(uuid, fields, cards):
    url = f"https://api.crunchbase.com/api/v4/entities/investments/${uuid}"
    params = {}
    if cards:
        params["card_ids"] = cards
    headers = {
        "accept": "application/json",
        "X-Cb-User-Key": CRUNCHBASE_API_KEY
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.RequestException as error:
        print(f"Error fetching organization data for UUID {uuid}: {error}")
        return None

def crunchbasefundroundlookup(uuid, fields, cards):
    url = f"https://api.crunchbase.com/api/v4/entities/funding_rounds/${uuid}"
    params = {}
    if cards:
        params["card_ids"] = cards
    if fields:
        params["field_ids"] = fields
    headers = {
        "accept": "application/json",
        "X-Cb-User-Key": CRUNCHBASE_API_KEY
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.RequestException as error:
        print(f"Error fetching organization data for UUID {uuid}: {error}")
        return None

def crunchbasefundlookup(uuid, fields, cards):
    url = f"https://api.crunchbase.com/api/v4/entities/funds/${uuid}"
    params = {}
    if cards:
        params["card_ids"] = cards
    if fields:
        params["field_ids"] = fields
    headers = {
        "accept": "application/json",
        "X-Cb-User-Key": CRUNCHBASE_API_KEY
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.RequestException as error:
        print(f"Error fetching organization data for UUID {uuid}: {error}")
        return None
    
def crunchbaseipolookup(uuid, fields, cards):
    url = f"https://api.crunchbase.com/api/v4/entities/ipos/${uuid}"
    params = {}
    if cards:
        params["card_ids"] = cards
    if fields:
        params["field_ids"] = fields
    headers = {
        "accept": "application/json",
        "X-Cb-User-Key": CRUNCHBASE_API_KEY
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.RequestException as error:
        print(f"Error fetching organization data for UUID {uuid}: {error}")
        return None
    
def fetch_organization_data(uuid, headers, entity_def_id):
    """Fetch detailed data for the organization using UUID."""
    url = f"https://api.crunchbase.com/api/v4/entities/organizations/{uuid}"
    
    params = {
        "cards": (
        "acquiree_acquisitions,acquirer_acquisitions,child_organizations,"
        "child_ownerships,event_appearances,fields,founders,headquarters_address,"
        "investors,ipos,jobs,key_employee_changes,layoffs,parent_organization,"
        "parent_ownership,participated_funding_rounds,participated_funds,"
        "participated_investments,press_references,raised_funding_rounds,"
        "raised_funds,raised_investments"
        )
    }
    

    print("Entity Def ID:", entity_def_id)

    if entity_def_id == "organization":
        response = crunchbaseorglookup(uuid, "", params)
    elif entity_def_id == "investment":
        response = crunchbaseinvestlookup(uuid, "", "fields,funding_round,investor,organization,partner")
    elif entity_def_id == "funding_round":
        response = crunchbasefundroundlookup(uuid, "money_raised,updated_at,identifier", "fields,investments,investors,lead_investors,organization,partners,press_references")
    elif entity_def_id == "fund":
        response = crunchbasefundlookup(uuid, "", "fields,investors,owner,press_references")
    elif entity_def_id == "ipo":
        response = crunchbaseipolookup(uuid, "", "fields,organization,press_references")
    elif entity_def_id == "jobs":
        response = None
    else:
        print("Invalid entity type")
        response = None
    # response = requests.get(url, headers=headers, params=params)
    if response:
        print(f"Successfully fetched data for UUID: {uuid}")
        print("Response:")
        return response
    
    return None

def extract_and_parse_data(data):
    """Extract and parse specific fields from the Crunchbase data."""
    fields = data.get('cards', {}).get('fields', {})

    # Example parsing for revenue range
    revenue_range = fields.get('revenue_range')
    parsed_revenue = parse_revenue_range(revenue_range) if revenue_range else "Unknown"

    # Extract other relevant fields and perform parsing or processing
    organization_name = data.get('properties', {}).get('identifier', {}).get('value')
    description = fields.get('description', 'No description available')
    location = parse_location(data.get('cards', {}).get('headquarters_address', [None])[0])
    funding_total = fields.get('funding_total', {}).get('value_usd', 'Unknown')

    final_data = {
        'organization_name': organization_name,
        'description': description,
        'location': location,
        'revenue': parsed_revenue,
        'funding_total_usd': funding_total,
        'industries': parse_industries(fields),
        'categories': parse_categories(fields),
        'employeeCount': parse_employee_count(fields.get('num_employees_enum')),
        'ipos': parse_ipos(data),
        'acquirer_acquisitions': parse_acquirer_acquisitions(data),
        'acquiree_acquisitions': parse_acquiree_acquisitions(data),
        'investments': data.get('cards', {}).get('raised_investments', [])
    }
    print("Final Data:")
    print(final_data)
    return final_data

def parse_location(headquarters):
    """Parse location details from the headquarters information."""
    if not headquarters:
        return {}
    return {
        'city': next((loc.get('value') for loc in headquarters.get('location_identifiers', []) if loc.get('location_type') == 'city'), None),
        'region': next((loc.get('value') for loc in headquarters.get('location_identifiers', []) if loc.get('location_type') == 'region'), None),
        'country': next((loc.get('value') for loc in headquarters.get('location_identifiers', []) if loc.get('location_type') == 'country'), None),
        'street': headquarters.get('street_1'),
        'country_code': headquarters.get('country_code'),
        'region_code': headquarters.get('region_code'),
        'postal_code': headquarters.get('postal_code'),
    }

def parse_industries(fields):
    """Parse industries from fields."""
    return [group.get('value') for group in fields.get('category_groups', [])]

def parse_categories(fields):
    """Parse categories from fields."""
    return [category.get('value') for category in fields.get('categories', [])]

def parse_employee_count(employee_count_enum):
    """Dummy employee count parsing (implement as needed)."""
    return employee_count_enum

def parse_ipos(data):
    """Parse IPO data."""
    return [{
        'description': ipo.get('short_description'),
        'went_public_on': ipo.get('went_public_on'),
        'stock_symbol': ipo.get('stock_full_symbol')
    } for ipo in data.get('cards', {}).get('ipos', [])]

def parse_acquirer_acquisitions(data):
    """Parse acquisitions made by the organization."""
    return [{
        'name': itm.get('identifier', {}).get('value'),
        'permalink': itm.get('identifier', {}).get('permalink'),
        'announced_on': itm.get('announced_on', {}).get('value'),
        'price': itm.get('price'),
        'short_description': itm.get('short_description'),
    } for itm in data.get('cards', {}).get('acquirer_acquisitions', [])]

def parse_acquiree_acquisitions(data):
    """Parse acquisitions where the organization was acquired."""
    return [{
        'name': itm.get('identifier', {}).get('value'),
        'permalink': itm.get('identifier', {}).get('permalink'),
        'short_description': itm.get('short_description'),
        'announced_on': itm.get('announced_on', {}).get('value'),
    } for itm in data.get('cards', {}).get('acquiree_acquisitions', [])]
  
def generate_query(api_key, sub_task, context):
    print(f"Generating query for sub-task: {sub_task}")
    refined_queries = generate_google_search_query(api_key, sub_task, context)
    all_results = []
    api_key = "AIzaSyDsAx4S4TFMiZmoXaawGs9rWB0Ceukaodw"
    for query in refined_queries:
        print(f"Processing query: {query}")
        search_results = google_search(query, api_key, cse_id="1707823c3c6f84768")
        if search_results:
            non_linkedin_urls = [result['link'] for result in search_results if "linkedin.com" not in result['link']][:10]
            if non_linkedin_urls:
                body_contents = get_body_content_with_scraperapi(non_linkedin_urls, scraperapi_key="ce62f4c1ef87f306e5f0288b88778ff8")
                combined_content = "\n\n".join(content for content in body_contents.values() if content)
                if combined_content:
                    summarized_content = summarize_content( query, combined_content)
                    all_results.append(summarized_content)
                else:
                    all_results.append("No content was extracted.")
            else:
                all_results.append("No non-LinkedIn URLs found.")
        else:
            all_results.append("No results found for query: " + query)
    
    # Combine all summarized contents or return them as a list
    final_result = "\n\n".join(all_results) if all_results else "No results found for any query."
    final_result = summarize_content(sub_task, final_result)
    return final_result


# Internal function to generate a Google search query
def generate_google_search_query(api_key, sub_task, context):
    system_prompt = f"""
    You are an AI assistant specializing in generating effective search queries for web research. Given a sub-task, generate a simplified and precise search query or multiple queries to pass to Google to yield relevant results in a web search. Wherever possible, generate only a single query. Restrict multiple queries mostly to cases if the context contains a list of entities (e.g., companies, people), generate separate queries for each entity based on the sub-task. Return all generated queries as an array of strings.
    The query must be as short as possible while still being effective. Strictly Do not include words such as current, today, today's date and so on because the context will be provided in the search.
    """
    user_prompt = f"sub-task: '{sub_task}' \n context: '{context}'"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=150,
        temperature=0.1
    ).choices[0].message.content.strip()

    try:
        # Attempt to parse the response as JSON
        refined_queries = json.loads(response)
    except json.JSONDecodeError:
        # If the response is not JSON, treat it as plain text
        refined_queries = [query.strip().strip('"') for query in response.split('\n') if query.strip()]

    # Ensure the result is a list of strings
    if isinstance(refined_queries, str):
        refined_queries = [refined_queries]
    elif isinstance(refined_queries, list):
        refined_queries = [query.strip().strip('"') for query in refined_queries if isinstance(query, str)]

    #remove ```json, ```, [, ] from refined_queries
    refined_queries = [query.replace("```json", "").replace("```", "").replace("[", "").replace("]", "").strip() for query in refined_queries]
    
    #final_refined_queries = refined-queries which are not empty
    refined_queries = [query for query in refined_queries if query]
    print(f"Generated Google Search Queries: {refined_queries}")
    return refined_queries

# Function to scrape content using ScraperAPI
def get_body_content_with_scraperapi(urls, scraperapi_key, retries=3):
    content_dict = {}
    count = 0
    for i, url in enumerate(urls):
        if count == 2:
            break
        for attempt in range(retries):
            try:
                print(f"Fetching content from: {url} using ScraperAPI (Attempt {attempt + 1})")
                response = requests.get(f"http://api.scraperapi.com", 
                                        params={"api_key": scraperapi_key, "url": url, "render": "true"}, 
                                        timeout=60)
                if response.status_code == 500:
                    print(f"Error 500 for URL {url} on attempt {attempt + 1}. Retrying...")
                    time.sleep(2)  # Wait before retrying
                    continue  # Retry on 500 error

                if response.status_code != 200:
                    print(f"Error: {response.status_code} for URL {url}")
                    content_dict[url] = None
                    break

                # Parse the HTML content
                soup = BeautifulSoup(response.text, 'html.parser')
                body_content = soup.body.get_text(separator='\n').strip()
                clean_content = "\n".join([line for line in body_content.splitlines() if line.strip() != ""])
                content_dict[url] = clean_content
                print(f"Successfully fetched and parsed content from: {url}")
                count += 1
                break  # Break out of retry loop if successful

            except Exception as e:
                print(f"Failed to fetch content from {url} on attempt {attempt + 1}: {e}")
                if attempt + 1 == retries:
                    content_dict[url] = None
                    print(f"All retries failed for URL {url}. Moving on.")
                else:
                    time.sleep(2)  # Wait before retrying

    return content_dict

# Function to summarize the content from scraped results
def summarize_linkedin(linkedin_data):
    system_prompt = f"""
    You are an AI assistant that specializes in summarizing information from LinkedIn profiles. Given the extracted LinkedIn data, summarize the key details such as location, experience, skills, education, job title, certitfications, companies, emails, industries, and more in a concise and informative manner. Ensure that the summary is clear, accurate, and relevant to the user query. Answer with respect to today's date which is {date}.
    Strictly provide every single skill, location, experience, education, job title, certification, company, email, industry, and other details that are present in the LinkedIn data. If any of the details are missing, do not provide them in the summary.
    """
    user_prompt = f"LinkedIn data: '{linkedin_data}'."

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1000,
        temperature=0.5
    ).choices[0].message.content.strip()

    return response

def summarize_content(query, additional_text):
    system_prompt = f"""
    You will be given a query and a lot of text. Your task is to analyze the text properly and answer the query accordingly. The text might be taken from relevant URLs on the web and so could have a lot of extra information too. Analyze just the relevant text and answer the query accordingly. Properly format the output. It must not look web scraped. Output must be a summary of what was found in the text. Also output which URL the text was generated from if it is provided in the text. Dont mention a source if it is not available. The output must strictly be in plaintext format. Answer with respect to today's date which is {date}.
    """
    user_prompt = f'query: "{query}":\n\ntext: {additional_text}.'

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2000,
        temperature=0.2
    ).choices[0].message.content.strip()

    return response

def summarize_content_final(query, additional_text):
    system_prompt = f"""
    You will be given a query and a lot of text. Your task is to analyze the text properly and answer the query accordingly. The text is a summary of the results from all the sub tasks associated with the query. Analyze the text and answer the query accordingly. Properly format the output. Output must be a summary of what was found in the text. If query can be answered in one or two lines, output one or two lines only. Also output which URL the text was generated from if they are provided in the text. Strictly Do Not mention that the source is not available. The output must strictly be in plaintext format. Answer with respect to today's date which is {date}.
    Strictly output the content in the format as shown in the sample output. If the source is not available, do not output the source.
    Only the format must be as shown, the size of the output can vary. Sample Output:

    HireQuotient offers the following products and services:
    1. EasySource - An AI-powered candidate sourcing tool
    2. EasyAssess - A candidate assessment tool that evaluates candidates on real-life, future-focused assessments
    3. EasyInterview - A video interview software
    4. Managed sourcing solution - A service to help companies source and assess top talent HireQuotient also provides an "end to end recruitment automation platform for Non-tech Hiring" and helps companies with talent acquisition, skill assessment, and video interviewing.
    Sources: https://www.hirequotient.com/

    """
    user_prompt = f'query: "{query}":\n\ntext: {additional_text}.'

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2000,
        temperature=0.2
    ).choices[0].message.content.strip()

    return response

def generate_column_name(query, csv_file):
    # Read the CSV file using pandas
    df = pd.read_csv(csv_file)
    # store all column names in an array
    column_names = df.columns

    system_prompt = f"""
    You will be given a query. Just return a simple one line of few words which can be used as a column name for the answer to the query. You will also be provided with existing column names. Make sure the generated column name is not already present.
    Do not include any special characters in the column name.
    """

    user_prompt = f"Query: '{query}' \n Existing Column Names: {column_names}"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=50,
        temperature=0.7
    ).choices[0].message.content.strip()

    return response

# Function to update the persistent context
def update_context(sub_task, results):
    global persistent_context  # Access the global persistent context
    persistent_context = persistent_context + "\n" + results
    # Add more conditions as needed to update the context

def convert_to_plaintext(text):
    system_prompt = f"""
    You will be given somme text. Your task is to convert the text to plaintext format if it is markdown or any other format. Do not change the content of the text. Just convert it to plaintext format. The output must strictly be in plaintext format.
    This is done by replacing and removing any markdown or special characters in the text. Strictly output just the text in plaintext format. If it is already in plaintext format, strictly output the same text.
    """
    user_prompt = f'text: "{text}"'

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1000,
        temperature=0.2
    ).choices[0].message.content.strip()

    return response

def main(user_query):       
    # Break down the task into sub-tasks
    sub_tasks = break_down_task(user_query)

    # Execute each sub-task using the agent
    final_results = []
    for sub_task in sub_tasks:
        result = agent_execute_sub_task(sub_task)
        final_results.append(result)
    
    # compile the final results into a single response
    final_response = "\n".join(final_results)

    response = summarize_content_final(user_query, final_response)
    print("Final Response:")
    print(response)
    return response

def generate_from_csv(csv_file, query_template):
    # Read the CSV file using pandas
    df = pd.read_csv(csv_file)

    col_name = generate_column_name(query_template, csv_file)
    # Initialize a new 'Response' column with empty strings or appropriate default values
    df[col_name] = pd.NA

    # Find placeholders in the query template
    placeholders = re.findall(r'\{(.*?)\}', query_template)

    for placeholder in placeholders:
        if placeholder in df.columns:
            # Iterate over each row, replace the placeholder, and generate the query
            for index, row in df.iterrows():
                # Replace the placeholder with the actual data from the CSV column
                user_query = query_template.replace(f"{{{placeholder}}}", str(row[placeholder]))
                # Execute the query (assuming main is defined to process this query)
                global persistent_context
                persistent_context = ""
                response = main(user_query)  # This function needs to be defined to handle the query
                # Store the response in the 'Response' column
                df.at[index, col_name] = response

    # Save the updated DataFrame to a new CSV file
    df.to_csv(csv_file, index=False)

if __name__ == "__main__":
    query_template = "Who is the CEO of {Company_name}?"
    csv_file = 'company.csv'

    generate_from_csv(csv_file, query_template)
