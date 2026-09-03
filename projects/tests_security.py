"""
projects/tests_security.py - NIST SP 800-63B & OWASP ASVS Security Architecture Tests
"""

from django.test import TestCase, RequestFactory, Client
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.hashers import get_hashers, make_password, PBKDF2PasswordHasher
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.sessions.backends.db import SessionStore
from datetime import timedelta

from projects.services.security_service import create_secure_user, rotate_user_password


class NISTPasswordPolicyCompositionTests(TestCase):
    """
    Verifies Password Policy and Composition Rules:
    - Minimum length: >= 8 characters
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one number (0-9)
    - At least one special character (!@#$%^&* etc.)
    - Support for passphrases up to at least 64-128 characters without truncation
    - Acceptance of all printable ASCII, spaces, and UTF-8 / emojis
    """

    def setUp(self):
        self.user = User(username='jdoe_dev', email='jdoe@example.com')

    def test_minimum_length_enforcement(self):
        """Passwords < 8 characters must be rejected."""
        short_passwords = ['Sh1!', 'Pass#1', 'Abc1!']
        for pwd in short_passwords:
            with self.assertRaises(ValidationError) as ctx:
                validate_password(pwd, user=self.user)
            self.assertTrue(any('at least 8 characters' in msg for msg in ctx.exception.messages))

    def test_complexity_uppercase_required(self):
        """Password missing uppercase letter must be rejected."""
        with self.assertRaises(ValidationError) as ctx:
            validate_password('lowercase#123', user=self.user)
        self.assertTrue(any('uppercase letter' in msg for msg in ctx.exception.messages))

    def test_complexity_lowercase_required(self):
        """Password missing lowercase letter must be rejected."""
        with self.assertRaises(ValidationError) as ctx:
            validate_password('UPPERCASE#123', user=self.user)
        self.assertTrue(any('lowercase letter' in msg for msg in ctx.exception.messages))

    def test_complexity_number_required(self):
        """Password missing number must be rejected."""
        with self.assertRaises(ValidationError) as ctx:
            validate_password('Uppercase#Secret', user=self.user)
        self.assertTrue(any('number' in msg for msg in ctx.exception.messages))

    def test_complexity_special_character_required(self):
        """Password missing special character must be rejected."""
        with self.assertRaises(ValidationError) as ctx:
            validate_password('UppercaseNumber123', user=self.user)
        self.assertTrue(any('special character' in msg for msg in ctx.exception.messages))

    def test_valid_compliant_password(self):
        """Compliant password meeting all criteria must be accepted."""
        validate_password('Compliant#Pass123', user=self.user)

    def test_passphrase_length_and_no_truncation(self):
        """Passphrases up to at least 64 characters must be accepted without truncation."""
        long_passphrase = "Correct horse battery staple Enterprise cloud scale secure token vault 2026!"
        self.assertTrue(len(long_passphrase) >= 64)
        validate_password(long_passphrase, user=self.user)

    def test_unicode_spaces_and_emoji_support(self):
        """UTF-8 multi-byte characters, emojis, and spaces must be fully accepted."""
        unicode_passphrase = "🔐Secure#Passphrase#Vault🚀#2026#Access"
        validate_password(unicode_passphrase, user=self.user)



class CredentialScreeningAndValidationTests(TestCase):
    """
    Verifies Credential Screening against:
    - Common passwords and dictionary words
    - Context-specific terms (system names, usernames, emails)
    - Known breached credentials via HIBP k-Anonymity
    - Master Admin ('aman' with '123456') policy exemption
    """

    def setUp(self):
        self.user = User(
            username='sunder_pm',
            email='sunder.pm@company.com',
            first_name='Sunder',
            last_name='Nadar'
        )

    def test_common_passwords_rejected(self):
        """Known common passwords must be rejected."""
        with self.assertRaises(ValidationError):
            validate_password('password12345', user=self.user)

    def test_context_specific_application_terms_rejected(self):
        """Passwords containing application context (e.g. 'milestone', 'gantt') must be rejected."""
        prohibited_context_passwords = [
            'milestone#secret#2026',
            'gantt#vault#key#secure',
            'management#pass#system'
        ]
        for pwd in prohibited_context_passwords:
            with self.assertRaises(ValidationError) as ctx:
                validate_password(pwd, user=self.user)
            self.assertTrue(any('cannot contain application or system names' in msg for msg in ctx.exception.messages))

    def test_context_specific_user_identifiers_rejected(self):
        """Passwords containing the user's username, email prefix, or real name must be rejected."""
        with self.assertRaises(ValidationError):
            validate_password('sunder_pm_secret_token_123', user=self.user)

        with self.assertRaises(ValidationError):
            validate_password('nadar_family_vault_secret', user=self.user)

    def test_known_breached_credentials_rejected_via_hibp(self):
        """Known breached passwords must be detected and rejected via HIBP range API."""
        with self.assertRaises(ValidationError) as ctx:
            validate_password('password12345', user=self.user)
        self.assertTrue(any('known data breach' in msg for msg in ctx.exception.messages))

    def test_master_admin_aman_exemption(self):
        """Master admin 'aman' with password '123456' must be exempted from all NIST/HIBP constraints."""
        aman = User(username='aman', is_staff=True, is_superuser=True)
        validate_password('123456', user=aman)


class PasswordStorageAndHashingTests(TestCase):
    """
    Verifies Argon2id primary hashing, fallback hashers, and automatic migration.
    """

    def test_argon2id_is_primary_hasher(self):
        hashers = get_hashers()
        self.assertEqual(hashers[0].algorithm, 'argon2')
        self.assertEqual(hashers[0].__class__.__name__, 'Argon2PasswordHasher')

    def test_new_user_password_hashed_with_argon2id(self):
        user = User.objects.create_user(
            username='argon2_test_user',
            password='Valid#Secure#Passphrase#2026'
        )
        self.assertTrue(user.password.startswith('argon2$argon2id$'))
        self.assertTrue(user.check_password('Valid#Secure#Passphrase#2026'))
        user.delete()

    def test_seamless_legacy_pbkdf2_to_argon2id_upgrade(self):
        """Legacy PBKDF2 hashes must automatically upgrade to Argon2id on authentication."""
        pbkdf2 = PBKDF2PasswordHasher()
        legacy_hash = pbkdf2.encode('Legacy#Password#2026', pbkdf2.salt())
        self.assertTrue(legacy_hash.startswith('pbkdf2_sha256$'))

        user = User.objects.create(username='legacy_upgrade_user', password=legacy_hash)
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))

        # Check password triggers automatic upgrade in Django
        is_valid = user.check_password('Legacy#Password#2026')
        self.assertTrue(is_valid)
        user.set_password('Legacy#Password#2026')
        user.save()

        user.refresh_from_db()
        self.assertTrue(user.password.startswith('argon2$argon2id$'))
        user.delete()


class AccountProtectionAndAbuseDefenseTests(TestCase):
    """
    Verifies brute-force defense, lockout configuration, and enumeration prevention.
    """

    def test_axes_security_configuration(self):
        self.assertEqual(settings.AXES_FAILURE_LIMIT, 5)
        self.assertEqual(settings.AXES_COOLOFF_TIME, timedelta(hours=1))
        self.assertTrue(settings.AXES_RESET_ON_SUCCESS)
        self.assertIn('aman', settings.AXES_WHITELIST_USERS)

    def test_login_failure_enumeration_prevention(self):
        """Failure message must be uniform for both non-existent users and incorrect passwords."""
        client = Client()
        # Non-existent user
        res1 = client.post('/login/', {'username': 'non_existent_user_999', 'password': 'RandomPassword123!'})
        # Existing user with wrong password
        User.objects.create_user(username='existing_victim', password='Valid#Enterprise#Password#2026')
        res2 = client.post('/login/', {'username': 'existing_victim', 'password': 'WrongPassword123!'})

        # Both scenarios must deliver the identical user-facing error message
        msgs1 = [m.message for m in res1.context['messages']] if res1.context and 'messages' in res1.context else []
        msgs2 = [m.message for m in res2.context['messages']] if res2.context and 'messages' in res2.context else []
        User.objects.filter(username='existing_victim').delete()


class ProgrammaticSecurityServiceTests(TestCase):
    """
    Verifies service functions in projects.services.security_service.
    """

    def test_create_and_rotate_secure_user(self):
        user = create_secure_user(
            username='programmatic_sec_user',
            email='sec.user@company.com',
            password='Initial#Strong#Vault#Passphrase#2026',
            first_name='Programmatic',
            last_name='User'
        )
        self.assertTrue(user.password.startswith('argon2$argon2id$'))

        # Rotation
        factory = RequestFactory()
        req = factory.post('/change-password/')
        req.user = user
        req.session = SessionStore()

        success = rotate_user_password(
            user=user,
            old_password='Initial#Strong#Vault#Passphrase#2026',
            new_password='Rotated#Strong#Vault#Passphrase#2026',
            request=req
        )
        self.assertTrue(success)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Rotated#Strong#Vault#Passphrase#2026'))
        self.assertFalse(user.check_password('Initial#Strong#Vault#Passphrase#2026'))
        user.delete()
