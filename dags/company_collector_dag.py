import os
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


def build_api_tasks(dag, limit=2000):
    """
    Dynamically builds tasks for API source scripts found in the api_source directory.
    Any new script added to that folder will automatically be picked up.
    """
    api_dir = "/opt/airflow/scripts/api_source"
    tasks = []
    if not os.path.exists(api_dir):
        return tasks
        
    for filename in sorted(os.listdir(api_dir)):
        if filename.endswith(".py") and not filename.startswith("_"):
            source_name = filename[:-3]  # Remove '.py'
            script_path = os.path.join(api_dir, filename)
            task = BashOperator(
                task_id=f"fetch_api_{source_name}",
                bash_command=f"python {script_path} --limit {limit}",
                dag=dag
            )
            tasks.append(task)
    return tasks


def build_scraper_tasks(dag):
    """
    Dynamically builds tasks for scraper scripts found in the scrapping directory.
    Any new scraper script added to that folder will automatically be picked up.
    """
    scraper_dir = "/opt/airflow/scripts/scrapping"
    tasks = []
    if not os.path.exists(scraper_dir):
        return tasks
        
    for filename in sorted(os.listdir(scraper_dir)):
        if filename.endswith(".py") and not filename.startswith("_"):
            source_name = filename[:-3]  # Remove '.py'
            script_path = os.path.join(scraper_dir, filename)
            task = BashOperator(
                task_id=f"scrape_{source_name}",
                bash_command=f"python {script_path}",
                dag=dag
            )
            tasks.append(task)
    return tasks


with DAG(
    'company_collector_dag',
    default_args=default_args,
    description='A dynamic, scalable pipeline fetching company data from API & scraper sources and normalizing it',
    schedule_interval='@weekly',
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=['company_collector'],
) as dag:

    # TaskGroup for API fetch tasks (run first, limited to 2000 each)
    with TaskGroup("api_tasks_group") as api_group:
        api_tasks = build_api_tasks(dag, limit=2000)

    # TaskGroup for scraper tasks (run second)
    with TaskGroup("scraper_tasks_group") as scraper_group:
        scraper_tasks = build_scraper_tasks(dag)

    # Establish dependency with a single, clean visual grouping line
    api_group >> scraper_group
