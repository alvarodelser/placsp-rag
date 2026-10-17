"""Isolated pilot that fully processes a sample of PLACSP expedientes.

Nothing here touches Weaviate, Neo4j or users.db: every byte the pilot
downloads or produces lands under one run directory, so its times and
volumes can be measured on their own.
"""
