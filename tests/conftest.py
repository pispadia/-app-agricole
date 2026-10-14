import pytest

import prix_marche


@pytest.fixture(autouse=True)
def vider_les_caches():
    """Chaque test part d'une base neuve : les caches en mémoire ne doivent pas déborder d'un test à l'autre."""
    prix_marche._cache.update(instant=0, valeur=None)
    yield
