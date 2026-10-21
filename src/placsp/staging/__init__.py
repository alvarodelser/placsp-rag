"""Staging area: the PLACSP ZIP archives as Parquet tables, the app's record of what PLACSP published.

download  ->  <data>/zips/<channel>/<file>.zip         (sources.py)
extract   ->  <data>/versions/<table>/<zip>.parquet     every entry version as published (extract.py)
build     ->  <data>/current/<table>.parquet            one row per tender, latest state (build.py)
"""
