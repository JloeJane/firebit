FROM clauten/elmfire:latest

# Pin numpy<2 to stay compatible with system GDAL Python bindings (gdal_calc.py)
RUN pip3 install --no-cache-dir "numpy>=1.24,<2.0" rasterio geopandas shapely

RUN mkdir -p /app/src
COPY src/ /app/src/

WORKDIR /app
CMD ["python3", "src/run_simulation.py"]
