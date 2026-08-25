import core
import pytest


class TestValidateName:
    @pytest.mark.parametrize("name", [
        "MonProjet",
        "Mon Projet 2024",
        "projet-01_final",
        "a" * core.MAX_NAME_LENGTH,
    ])
    def test_accepts_valid_names(self, name):
        core.validate_name(name)  # ne doit pas lever

    def test_strips_surrounding_whitespace_before_checking(self):
        core.validate_name("  Projet Valide  ")

    @pytest.mark.parametrize("name", ["", "   "])
    def test_rejects_empty_name(self, name):
        with pytest.raises(ValueError, match="vide"):
            core.validate_name(name)

    def test_rejects_name_too_long(self):
        with pytest.raises(ValueError, match="trop long"):
            core.validate_name("a" * (core.MAX_NAME_LENGTH + 1))

    @pytest.mark.parametrize("name", [
        "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b",
        ".", "..", "...", ".hidden",
    ])
    def test_rejects_forbidden_characters(self, name):
        with pytest.raises(ValueError, match="caractères non autorisés"):
            core.validate_name(name)
