# Stage A: Build Cell2Fire with Scott & Burgan (S&B) US fuel model support.
#
# We use fire2a/C2F-W instead of the main cell2fire/Cell2Fire repo because:
#   - Main repo implements Canadian FBP fire behavior system only
#   - C2F-W is the unified fork with --sim S flag for Scott & Burgan FBFM40 support
#   - Our fuel data is US FBFM40 codes 101-189, which C2F-W handles natively
#
# Build time: ~5-10 min (C++ compilation)

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    g++ make git \
    libtiff-dev libboost-dev \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone fire2a/C2F-W (Scott & Burgan + Kitral + FBP unified fork)
RUN git clone --depth 1 https://github.com/fire2a/C2F-W.git /opt/C2F-W

# Build the C++ binary
# Source lives in /opt/C2F-W/Cell2Fire/, binary outputs to same dir
WORKDIR /opt/C2F-W/Cell2Fire
RUN make

# Verify binary was produced
RUN test -f /opt/C2F-W/Cell2Fire/Cell2Fire && \
    echo "=== Cell2Fire binary OK ===" && \
    ls -lh /opt/C2F-W/Cell2Fire/Cell2Fire

# Stage the spain_lookup_table.csv at a fixed path so run_simulation.py can find it
RUN find /opt/C2F-W/data -name "spain_lookup_table.csv" -print -quit \
      | xargs -I{} cp {} /opt/C2F-W/spain_lookup_table.csv \
    && echo "Lookup table staged at /opt/C2F-W/spain_lookup_table.csv" \
    || echo "WARNING: spain_lookup_table.csv not found in data/"

# Python runtime deps
RUN pip3 install --no-cache-dir numpy rasterio geopandas shapely

WORKDIR /app
COPY src/ src/

CMD ["python3", "src/run_simulation.py"]
