"""
Ponto de entrada do servidor (uvicorn main:app).

A implementacao vive em thina.api.app; este modulo existe para compatibilidade
com scripts e documentacao que referenciam main:app.
"""

from thina.api.app import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
