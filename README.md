# Paraglide Manager 🪂

Outil d'aide à la planification de vols en parapente. Choisissez une zone sur la carte, un horizon
(30 min, 1 h, 2 h, 8 h, 12 h, 24 h, 48 h) et vos critères (durée de vol, niveau, thermiques) :
l'application croise prévisions multi-modèles, balises temps réel, sites FFVL / ParaglidingEarth et
espaces aériens pour proposer les meilleurs plans de vol, avec :

- un **briefing complet** (créneau, risques, aérologie, checklist, marges de finesse) ;
- une **carte interactive** avec route, atterrissages, espaces aériens et couches météo
  (vent par altitude, thermiques, plafond, base des nuages, CAPE, pluie) ;
- l'export **GPX** et **tâche XCTrack**.

> ⚠️ Outil d'aide à la décision : il ne remplace jamais l'analyse du pilote sur place,
> l'observation des conditions réelles ni les consignes du site.

## Démarrage rapide

```bash
# Backend (http://localhost:8000)
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000

# Frontend (http://localhost:5173)
cd frontend && npm install && npm run dev
```

Ou avec Docker : `docker compose up --build` → http://localhost:8080

Sans accès réseau aux sources, `DATA_MODE=mock` (backend) et `VITE_USE_MOCKS=true` (frontend)
permettent de tout faire tourner sur des données de démonstration.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Contrat d'API](docs/API_CONTRACT.md)
- [Cahier des charges pilote](docs/expert/cahier-des-charges-pilote.md)
- [backend/README.md](backend/README.md) — sources, variables d'env, algorithme
- [frontend/README.md](frontend/README.md)
