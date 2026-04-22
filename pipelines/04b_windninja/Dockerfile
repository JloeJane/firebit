FROM continuumio/miniconda3:latest

RUN conda install -y -c conda-forge windninja python=3.11 && \
    conda clean -afy

RUN pip install --no-cache-dir rasterio geopandas numpy

RUN mkdir -p /app/src
COPY src/ /app/src/

WORKDIR /app
CMD ["python", "src/run_windninja.py"]
