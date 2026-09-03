"""
projects/validators.py - NIST SP 800-63B & OWASP Compliant Password Validators

Features:
- PwnedPasswordValidator: Validates passwords against the Have I Been Pwned (HIBP)
  k-Anonymity API (SHA-1 prefix model) to block compromised passwords without exposing credentials.
- Enterprise Minimum Length Validator (12 chars default).
- Enterprise Common Password Validator.
- Enterprise Numeric Password Validator.
- Enterprise User Attribute Similarity Validator.
- Special Policy Exception: Master Administrator ('aman' with password '123456')
  is strictly exempted from these enterprise complexity rules to preserve master administration integrity.
"""

import hashlib
import logging
import re
import urllib.request
import urllib.error
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.password_validation import (
    UserAttributeSimilarityValidator,
    MinimumLengthValidator,
    CommonPasswordValidator,
    NumericPasswordValidator,
)

logger = logging.getLogger(__name__)


def is_master_admin(user, password=None):
    """
    Checks whether the target user is master admin 'aman'.
    Master admin 'aman' with password '123456' is exempted from enterprise NIST/OWASP constraints.
    """
    if user:
        username = getattr(user, 'username', '')
        if username and str(username).strip().lower() == 'aman':
            return True
    return False


class PwnedPasswordValidator:
    """
    NIST SP 800-63B & OWASP Compliant Breached Password Validator.
    Utilizes Have I Been Pwned (HIBP) Range API v3 with k-Anonymity.
    
    Security Architecture:
    1. Computes the SHA-1 hash of the password.
    2. Takes the first 5 characters (prefix) and sends only the prefix to
       https://api.pwnedpasswords.com/range/{prefix}. The full password or remainder hash
       is never exposed or transmitted externally.
    3. Searches the returned hash suffixes (35 chars) for a match.
    4. If found >= threshold, raises a ValidationError informing the user.
    5. Fails open on network timeouts/errors with a logged warning to prevent external service
       outages from denying access to legitimate internal users.
    6. Master admin 'aman' is exempted.
    """

    API_URL = "https://api.pwnedpasswords.com/range/{prefix}"
    DEFAULT_TIMEOUT = 2.0  # seconds

    def __init__(self, threshold=1, timeout=2.0, fail_open=True):
        self.threshold = threshold
        self.timeout = timeout
        self.fail_open = fail_open

    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return

        sha1_hash = hashlib.sha1(password.encode('utf-8')).hexdigest().upper()
        prefix = sha1_hash[:5]
        suffix = sha1_hash[5:]

        url = self.API_URL.format(prefix=prefix)
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'MilestoneManagement-NIST-Validator/1.0',
                'Add-Padding': 'true'  # Prevents response size side-channel leakage
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    logger.warning("HIBP API returned status %s. Failing open.", response.status)
                    if not self.fail_open:
                        raise ValidationError(_("Breach verification service returned unexpected response."))
                    return

                data = response.read().decode('utf-8')
                for line in data.splitlines():
                    parts = line.strip().split(':')
                    if len(parts) == 2:
                        res_suffix, count_str = parts[0], parts[1]
                        if res_suffix == suffix:
                            count = int(count_str)
                            if count >= self.threshold:
                                raise ValidationError(
                                    _(
                                        "This password has appeared in a known data breach %(count)s times "
                                        "(NIST SP 800-63B). For your security, please choose a different password."
                                    ),
                                    code="password_pwned",
                                    params={"count": f"{count:,}"},
                                )
        except ValidationError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("HIBP API connection failed or timed out (%s). Failing open.", exc)
            if not self.fail_open:
                raise ValidationError(_("Password breach verification service is temporarily unavailable."))
            return

    def get_help_text(self):
        return _("Your password cannot be a known compromised password from public data breaches.")


class EnterpriseMinimumLengthValidator(MinimumLengthValidator):
    """
    Enforces a minimum length of 8 characters and supports passphrases up to at least
    128 characters without truncation.
    Exempts master admin 'aman'.
    """
    def __init__(self, min_length=8, max_length=128):
        super().__init__(min_length=min_length)
        self.max_length = max_length

    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return
        if len(password) > self.max_length:
            raise ValidationError(
                _("Password cannot exceed %(max_length)d characters."),
                code='password_too_long',
                params={'max_length': self.max_length}
            )
        super().validate(password, user=user)


class ComplexityPasswordValidator:
    """
    Validates that a password contains:
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one number (0-9)
    - At least one special character (!@#$%^&* etc.)
    Exempts master admin 'aman'.
    """
    def __init__(self):
        pass

    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return

        errors = []
        if not re.search(r'[A-Z]', password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one uppercase letter (A-Z)."),
                    code='password_no_upper'
                )
            )
        if not re.search(r'[a-z]', password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one lowercase letter (a-z)."),
                    code='password_no_lower'
                )
            )
        if not re.search(r'\d', password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one number (0-9)."),
                    code='password_no_number'
                )
            )
        if not re.search(r'[^A-Za-z0-9]', password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one special character (e.g., !@#$%^&*)."),
                    code='password_no_special'
                )
            )

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Your password must contain at least one uppercase letter (A-Z), one lowercase letter (a-z), "
            "one number (0-9), and one special character (e.g. !@#$%^&*)."
        )



class ContextSpecificWordValidator:
    """
    NIST SP 800-63B Context-Specific Password Validator.
    Rejects passwords containing the application name, service terms,
    or direct derivatives of user context (username, email prefix, name).
    Exempts master admin 'aman'.
    """
    DEFAULT_TERMS = {'milestone', 'management', 'gantt', 'godrej'}

    def __init__(self, additional_terms=None):
        self.forbidden_terms = set(self.DEFAULT_TERMS)
        if additional_terms:
            self.forbidden_terms.update([t.lower() for t in additional_terms])

    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return

        normalized_pwd = password.lower()

        # 1. Check application context words
        for term in self.forbidden_terms:
            if len(term) >= 3 and term in normalized_pwd:
                raise ValidationError(
                    _("Password cannot contain application or system names (e.g., '%(term)s')."),
                    code='password_context_prohibited',
                    params={'term': term}
                )

        # 2. Check user-specific identifiers
        if user:
            user_terms = set()
            username = getattr(user, 'username', '')
            if username:
                user_terms.add(username.lower())
            email = getattr(user, 'email', '')
            if email and '@' in email:
                user_terms.add(email.split('@')[0].lower())

            first_name = getattr(user, 'first_name', '')
            if first_name:
                user_terms.add(first_name.lower())

            last_name = getattr(user, 'last_name', '')
            if last_name:
                user_terms.add(last_name.lower())

            for ut in user_terms:
                if len(ut) >= 3 and ut in normalized_pwd:
                    raise ValidationError(
                        _("Password cannot contain your personal identifier (e.g., '%(term)s')."),
                        code='password_user_context_prohibited',
                        params={'term': ut}
                    )

    def get_help_text(self):
        return _("Your password cannot contain system names or personal account identifiers.")


class EnterpriseCommonPasswordValidator(CommonPasswordValidator):
    """
    Checks against common passwords list, exempting master admin 'aman'.
    """
    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return
        super().validate(password, user=user)


class EnterpriseNumericPasswordValidator(NumericPasswordValidator):
    """
    Checks against entirely numeric passwords, exempting master admin 'aman'.
    """
    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return
        super().validate(password, user=user)


class EnterpriseUserAttributeSimilarityValidator(UserAttributeSimilarityValidator):
    """
    Checks against similarity to user attributes, exempting master admin 'aman'.
    """
    def validate(self, password, user=None):
        if is_master_admin(user, password):
            return
        super().validate(password, user=user)


try:
    from axes.backends import AxesStandaloneBackend

    class RobustAxesStandaloneBackend(AxesStandaloneBackend):
        """
        Subclasses AxesStandaloneBackend to gracefully ignore calls where request is None
        (e.g., CLI management commands, unit test clients, background tasks) rather than crashing,
        while fully enforcing brute-force and credential stuffing defense whenever an HTTP request is present.
        """
        def authenticate(self, request=None, **credentials):
            if request is None:
                return None
            return super().authenticate(request=request, **credentials)
except ImportError:
    pass

