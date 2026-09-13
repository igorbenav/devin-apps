"""Tests for the deployment preflight checks."""

from unittest.mock import Mock

from src.infrastructure.config.settings import EnvironmentOption, Settings
from src.infrastructure.deploy.preflight import config_problems, expected_revision


def deployable_settings(**overrides) -> Settings:
    """A configuration preflight should have nothing to say about."""
    values = {
        "ENVIRONMENT": EnvironmentOption.PRODUCTION,
        "SECRET_KEY": "xF9mWqP3nL7vBfKsRt8HjZ2CyE5QaM6NuV4DgX1SpY7LwB9KzT3RhI0UoJ5PcA2MvS8",
        "POSTGRES_PASSWORD": "secure_db_password",
        "DATABASE_URL_OVERRIDE": None,
        "CREATE_TABLES_ON_STARTUP": False,
        "SESSION_BACKEND": "redis",
        "SESSION_SECURE_COOKIES": True,
        "CSRF_ENABLED": True,
        "CORS_ENABLED": True,
        "CORS_ORIGINS": "https://tools.example.com",
        "CORS_ALLOW_CREDENTIALS": True,
        "ADMIN_ENABLED": True,
        "ADMIN_USERNAME": "real_admin",
        "ADMIN_PASSWORD": "a_strong_admin_password_123",
        "CACHE_REDIS_HOST": "redis",
        "CACHE_REDIS_PORT": 6379,
        "CACHE_REDIS_PASSWORD": "redis_password",
        "RATE_LIMITER_REDIS_HOST": "redis",
        "RATE_LIMITER_REDIS_PORT": 6379,
        "RATE_LIMITER_REDIS_PASSWORD": "redis_password",
        "TASKIQ_REDIS_HOST": "redis",
        "TASKIQ_REDIS_PORT": 6379,
        "TASKIQ_REDIS_PASSWORD": "redis_password",
    }
    values.update(overrides)

    settings = Mock(spec=Settings)
    for key, value in values.items():
        setattr(settings, key, value)
    origins = values["CORS_ORIGINS"]
    settings.CORS_ORIGINS_LIST = [x.strip() for x in origins.split(",") if x.strip()] if origins else ["*"]

    return settings


class TestConfigProblems:
    def test_deployable_configuration_has_no_problems(self):
        assert config_problems(deployable_settings()) == []

    def test_non_production_environment_is_a_problem(self):
        problems = config_problems(deployable_settings(ENVIRONMENT=EnvironmentOption.DEVELOPMENT))

        assert [p.check for p in problems] == ["config"]
        assert "ENVIRONMENT" in problems[0].detail

    def test_create_tables_on_startup_is_a_problem(self):
        problems = config_problems(deployable_settings(CREATE_TABLES_ON_STARTUP=True))

        assert any("CREATE_TABLES_ON_STARTUP" in p.detail for p in problems)

    def test_reports_the_same_issues_that_would_stop_a_production_start(self):
        problems = config_problems(deployable_settings(SECRET_KEY="secret", CSRF_ENABLED=False))

        details = " ".join(p.detail for p in problems)
        assert "SECRET_KEY" in details
        assert "CSRF" in details


class TestSharedRedisPassword:
    def test_same_server_with_a_different_password_is_a_problem(self):
        problems = config_problems(deployable_settings(TASKIQ_REDIS_PASSWORD=None))

        assert any("TASKIQ_REDIS_PASSWORD" in p.detail for p in problems)

    def test_a_separate_server_may_have_its_own_password(self):
        assert config_problems(deployable_settings(TASKIQ_REDIS_HOST="queue.example.com")) == []


class TestExpectedRevision:
    def test_reads_the_migration_head_shipped_with_the_code(self):
        assert expected_revision() is not None
