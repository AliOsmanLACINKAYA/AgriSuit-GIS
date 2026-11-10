"""Read-only agriculture eligibility API."""
import json
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request
from psycopg2 import Error
from psycopg2.pool import ThreadedConnectionPool
from pydantic import BaseModel, ConfigDict, Field


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = ThreadedConnectionPool(1, 8, os.environ["DATABASE_URL"],
                                            connect_timeout=5,
                                            options="-c statement_timeout=5000")
    try:
        yield
    finally:
        app.state.pool.closeall()


app = FastAPI(title="AgriSuit GIS API", lifespan=lifespan)
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Position = tuple[Longitude, Latitude]
Ring = Annotated[list[Position], Field(min_length=4, max_length=1000)]
Polygon = Annotated[list[Ring], Field(min_length=1, max_length=32)]
RegionCode = Annotated[str, Path(min_length=1, max_length=128)]


class PolygonGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Polygon"]
    coordinates: Polygon


class MultiPolygonGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["MultiPolygon"]
    coordinates: Annotated[list[Polygon], Field(min_length=1, max_length=16)]


class Eligibility(BaseModel):
    status: Literal["open", "closed", "outside_region"]
    is_open: bool


def query(request: Request, sql: str, parameters: tuple = ()) -> str:
    pool = request.app.state.pool
    connection = None
    try:
        connection = pool.getconn()
        with connection, connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            return cursor.fetchone()[0]
    except Error as exc:
        raise HTTPException(503, "Database unavailable") from exc
    finally:
        if connection is not None:
            pool.putconn(connection, close=bool(connection.closed))


def eligibility(status: str) -> Eligibility:
    failures = {
        "unknown_region": (404, "Unknown region"),
        "invalid_geometry": (422, "Invalid WGS84 geometry"),
        "mask_unavailable": (503, "Refresh the agricultural mask"),
    }
    if status in failures:
        raise HTTPException(*failures[status])
    return Eligibility(status=status, is_open=status == "open")


@app.get("/health")
def health(request: Request):
    query(request, "SELECT 1")
    return {"status": "ok"}


@app.get("/regions/{region_code}/eligibility/point", response_model=Eligibility)
def point(region_code: RegionCode, request: Request,
          lon: Annotated[float, Query(ge=-180, le=180)],
          lat: Annotated[float, Query(ge=-90, le=90)]):
    return eligibility(query(request, "SELECT public.agriculture_point_status(%s, %s, %s)",
                             (region_code, lon, lat)))


@app.post("/regions/{region_code}/eligibility/polygon", response_model=Eligibility)
def polygon(region_code: RegionCode, geometry: PolygonGeometry | MultiPolygonGeometry,
            request: Request):
    polygons = [geometry.coordinates] if geometry.type == "Polygon" else geometry.coordinates
    if sum(len(ring) for part in polygons for ring in part) > 10000:
        raise HTTPException(422, "Geometry exceeds 10000 vertices")
    if any(ring[0] != ring[-1] for part in polygons for ring in part):
        raise HTTPException(422, "Polygon rings must be closed")
    return eligibility(query(request,
                             "SELECT public.agriculture_status(%s, ST_GeomFromGeoJSON(%s))",
                             (region_code, json.dumps(geometry.model_dump()))))
