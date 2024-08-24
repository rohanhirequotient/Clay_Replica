# Clay_Replica
Replica of Clay

## Step - 1 
- Once repo is downloaded, run the command pip3 install -r requirements.txt.

## Step - 2
- Replace openai_api_key in line 17 of agents.py with the actual key.

## How to run - 
- At the end of the file agents.py, there is a line called query_template = "" and another line called csv_file = ''.
- Replace the csv_file, with the csv file you want to populate.
- Replace that with the query of your choice. The column name you want to use must be within {}.
- Example: 
    query_template = "Who is the CEO of {Company_name}?"
    csv_file = 'company.csv'

    Company_name is a column in the file company.csv

- Once done, run the command python3 agents.py.
