"""
Régression : `run_health_check()` affichait un avertissement
« GitHub OAuth non configuré » à chaque démarrage dès que
`app_config.github_client_id` était vide, même quand un compte GitHub
était réellement connecté (device flow ou GitHub App). L'utilisateur
percevait ça comme "l'app dit que je ne suis pas connecté".
"""

import core


class TestGithubHealthCheckNotification:
    def test_warns_when_nothing_configured(self, isolated_data_dir):
        result = core.run_health_check()
        titles = [i.title for i in result.issues]
        assert "GitHub OAuth non configuré" in titles

    def test_no_warning_when_oauth_account_connected(self, isolated_data_dir):
        core.save_github_account(
            token="ghp_faketoken",
            user_info={"login": "octocat", "name": "The Octocat", "avatar_url": ""},
        )
        result = core.run_health_check()
        titles = [i.title for i in result.issues]
        assert "GitHub OAuth non configuré" not in titles

    def test_no_warning_when_github_app_configured(self, isolated_data_dir):
        core.set_github_app_config(
            app_id="12345",
            private_key_pem="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
            installation_id="67890",
        )
        result = core.run_health_check()
        titles = [i.title for i in result.issues]
        assert "GitHub OAuth non configuré" not in titles

    def test_no_warning_when_notice_hidden_by_user(self, isolated_data_dir):
        app_cfg = core.get_app_config()
        app_cfg["hide_github_not_connected"] = True
        core.set_app_config(app_cfg)

        result = core.run_health_check()
        titles = [i.title for i in result.issues]
        assert "GitHub OAuth non configuré" not in titles
