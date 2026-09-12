from io import BytesIO

from werkzeug.datastructures import FileStorage

from app import app, encoder_photo, prix_valide, quantite_valide


def test_quantite_accepte_une_valeur_et_unite():
    assert quantite_valide("20 kg") == "20 kg"


def test_quantite_refuse_une_chaine_libre():
    try:
        quantite_valide("beaucoup")
    except ValueError:
        pass
    else:
        raise AssertionError("Une quantité non numérique doit être refusée.")


def test_prix_accepte_le_format_fcfa():
    assert prix_valide("500 FCFA / kg") == "500 FCFA / kg"


def test_photo_invalide_refusee():
    fichier = FileStorage(stream=BytesIO(b"pas une image"), filename="photo.jpg")
    with app.test_request_context():
        assert encoder_photo(fichier) is None
