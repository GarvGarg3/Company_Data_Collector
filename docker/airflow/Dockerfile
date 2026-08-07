FROM apache/airflow:2.8.1

USER root

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
    libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements.txt /requirements.txt

# Dynamically construct constraint URL based on python version inside the container
RUN PYTHON_VERSION="$(python --version | cut -d ' ' -f 2 | cut -d '.' -f 1-2)" && \
    pip install --no-cache-dir \
    -r /requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.8.1/constraints-${PYTHON_VERSION}.txt"
