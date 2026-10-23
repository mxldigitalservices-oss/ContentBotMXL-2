"""
core/asset_manager.py
Gestiona el banco de imagenes del robot MXL ubicado en assets/mxl_robot/.
Indexa las imagenes por categoria/emocion y expone funciones de seleccion
para el proceso de ensamblaje de video.
"""

import random
import logging
from pathlib import Path
from collections import defaultdict

from config.settings import settings

logger = logging.getLogger(__name__)

# Extensiones de imagen validas para este proyecto
VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Carpeta especifica donde viven las imagenes clasificadas del robot
MXL_ROBOT_DIR = settings.ASSETS_DIR / "mxl_robot"


class AssetManager:
    """Indexa y selecciona imagenes del robot MXL por categoria/emocion."""

    def __init__(self, robot_dir: Path = MXL_ROBOT_DIR):
        self.robot_dir = robot_dir
        self._index: dict[str, list[Path]] = defaultdict(list)
        self._loaded = False

    def load(self) -> "AssetManager":
        """Escanea robot_dir y construye el indice categoria -> lista de imagenes."""
        if not self.robot_dir.exists():
            raise FileNotFoundError(
                f"No se encontro la carpeta de imagenes del robot en {self.robot_dir}"
            )

        self._index.clear()

        for category_dir in sorted(self.robot_dir.iterdir()):
            if not category_dir.is_dir():
                continue

            category = category_dir.name
            images = sorted(
                p for p in category_dir.iterdir()
                if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS
            )

            if images:
                self._index[category] = images
            else:
                logger.warning("Categoria '%s' no tiene imagenes validas.", category)

        if not self._index:
            raise FileNotFoundError(
                f"No se encontraron categorias con imagenes en {self.robot_dir}"
            )

        self._loaded = True
        return self

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    @property
    def categories(self) -> list[str]:
        """Lista de categorias/emociones disponibles."""
        self._ensure_loaded()
        return sorted(self._index.keys())

    def count_by_category(self) -> dict[str, int]:
        """Devuelve cuantas imagenes hay por categoria."""
        self._ensure_loaded()
        return {cat: len(imgs) for cat, imgs in self._index.items()}

    def total_count(self) -> int:
        """Total de imagenes indexadas en todas las categorias."""
        self._ensure_loaded()
        return sum(len(imgs) for imgs in self._index.values())

    def get_random_asset(self, category: str | None = None) -> Path:
        """
        Devuelve una imagen aleatoria.
        Si se especifica category, la elige solo de esa categoria/emocion.
        Si no, elige una categoria al azar y luego una imagen dentro de ella.
        """
        self._ensure_loaded()

        if category is not None:
            if category not in self._index:
                raise ValueError(
                    f"Categoria '{category}' no existe. Disponibles: {self.categories}"
                )
            return random.choice(self._index[category])

        chosen_category = random.choice(self.categories)
        return random.choice(self._index[chosen_category])

    def get_random_sequence(self, category: str, count: int) -> list[Path]:
        """
        Devuelve una secuencia de 'count' imagenes de una categoria, sin repetir
        mientras sea posible. Si count supera el numero de imagenes disponibles,
        se repiten aleatoriamente para completar la cantidad pedida.
        """
        self._ensure_loaded()

        if category not in self._index:
            raise ValueError(
                f"Categoria '{category}' no existe. Disponibles: {self.categories}"
            )

        available = self._index[category]

        if count <= len(available):
            return random.sample(available, count)

        # count > imagenes disponibles: se permite repetir
        sequence = available.copy()
        random.shuffle(sequence)
        while len(sequence) < count:
            sequence.append(random.choice(available))
        return sequence[:count]

    def get_all_in_category(self, category: str) -> list[Path]:
        """Devuelve todas las imagenes de una categoria, en orden."""
        self._ensure_loaded()
        if category not in self._index:
            raise ValueError(
                f"Categoria '{category}' no existe. Disponibles: {self.categories}"
            )
        return list(self._index[category])


# Instancia lista para importar directamente: from core.asset_manager import asset_manager
asset_manager = AssetManager()
