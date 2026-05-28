"""Comandos no PC Windows (apps, sites, Spotify)."""

from thina.pc.actions import abrir_aplicativo, abrir_site, try_pc_fastpath
from thina.pc.spotify import controlar_spotify, try_spotify_fastpath

__all__ = [
    "abrir_aplicativo",
    "abrir_site",
    "controlar_spotify",
    "try_pc_fastpath",
    "try_spotify_fastpath",
]
