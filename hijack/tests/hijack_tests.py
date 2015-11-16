import sys

import django
from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.template import Template, Context
from django.test import TestCase, Client
from compat import unquote_plus

from hijack.admin import HijackUserAdmin
from hijack.helpers import is_authorized
from hijack import settings as hijack_settings
from hijack.tests.utils import SettingsOverride

class HijackTests(TestCase):

    def setUp(self):
        self.superuser_username = 'superuser'
        self.superuser_email = 'superuser@example.com'
        self.superuser_password = 'superuser_pw'
        self.superuser = User.objects.create_superuser(self.superuser_username, self.superuser_email, self.superuser_password)

        self.staff_user_username = 'staff_user'
        self.staff_user_email = 'staff_user@example.com'
        self.staff_user_password = 'staff_user_pw'
        self.staff_user = User.objects.create_user(self.staff_user_username, self.staff_user_email, self.staff_user_password)
        self.staff_user.is_staff = True
        self.staff_user.save()

        self.user_username = 'user'
        self.user_email = 'user@example.com'
        self.user_password = 'user_pw'
        self.user = User.objects.create_user(self.user_username, self.user_email, self.user_password)

        self.client = Client()
        self.client.login(username=self.superuser_username, password=self.superuser_password)

    def tearDown(self):
        self.client.logout()

    def test_basic_hijack(self):
        client = Client()
        client.login(username=self.superuser_username, password=self.superuser_password)
        hijacked_response = client.get('/hijack/%d/' % self.user.id, follow=True)
        self.assertEqual(hijacked_response.status_code, 200)
        hijack_released_response = client.get('/hijack/release-hijack/', follow=True)
        self.assertEqual(hijack_released_response.status_code, 200)
        client.logout()

    def assertHijackSuccess(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.session['is_hijacked_user'])
        self.assertTrue('hijacked-warning' in str(response.content))
        self.assertFalse('Log in' in str(response.content))

    def assertHijackPermissionDenied(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertFalse(getattr(self.client.session, 'is_hijacked_user', False))
        self.assertFalse('hijacked-warning' in str(response.content))

    def _hijack(self, user_id):
        return self.client.get('/hijack/%d/' % user_id, follow=True)

    def _release_hijack(self):
        response = self.client.get('/hijack/release-hijack/', follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse('hijacked-warning' in str(response.content))
        return response

    def test_hijack_urls(self):
        self.assertEqual('/hijack/disable-hijack-warning/', reverse('disable_hijack_warning'))
        self.assertEqual('/hijack/release-hijack/', reverse('release_hijack'))
        self.assertEqual('/hijack/1/', reverse('login_with_id', args=[1]))
        self.assertEqual('/hijack/2/', reverse('login_with_id', kwargs={'user_id': 2}))
        self.assertEqual('/hijack/username/bob/', reverse('login_with_username', args=['bob']))
        self.assertEqual('/hijack/username/bob_too/', reverse('login_with_username', kwargs={'username': 'bob_too'}))
        self.assertEqual('/hijack/email/bob@bobsburgers.com/', unquote_plus(reverse('login_with_email', args=['bob@bobsburgers.com'])))
        self.assertEqual('/hijack/email/bob_too@bobsburgers.com/', unquote_plus(reverse('login_with_email', kwargs={'email': 'bob_too@bobsburgers.com'})))

    def test_hijack_url_user_id(self):
        response = self.client.get('/hijack/%d/' % self.user.id, follow=True)
        self.assertHijackSuccess(response)
        self._release_hijack()
        response = self.client.get('/hijack/%s/' % self.user.username, follow=True)
        self.assertEqual(response.status_code, 400)
        response = self.client.get('/hijack/-1/', follow=True)
        self.assertEqual(response.status_code, 404)

    def test_hijack_url_username(self):
        response = self.client.get('/hijack/username/%s/' % self.user_username, follow=True)
        self.assertHijackSuccess(response)
        self._release_hijack()
        response = self.client.get('/hijack/username/dfjakhdl/', follow=True)
        self.assertEqual(response.status_code, 404)

    def test_hijack_url_email(self):
        response = self.client.get('/hijack/email/%s/' % self.user_email, follow=True)
        self.assertHijackSuccess(response)
        self._release_hijack()
        response = self.client.get('/hijack/email/dfjak@hdl.com/', follow=True)
        self.assertEqual(response.status_code, 404)

    def test_hijack_permission_denied(self):
        self.client.logout()
        self.client.login(username=self.staff_user_username, password=self.staff_user_password)
        response = self._hijack(self.superuser.id)
        self.assertHijackPermissionDenied(response)
        response = self._hijack(self.staff_user.id)
        self.assertHijackPermissionDenied(response)
        response = self._hijack(self.user.id)
        self.assertHijackPermissionDenied(response)
        self.client.login(username=self.superuser_username, password=self.superuser_password)

    def test_release_before_hijack(self):
        response = self.client.get('/hijack/release-hijack/', follow=True)
        self.assertHijackPermissionDenied(response)

    def test_last_login_time_not_changed(self):
        self.client.logout()
        self.client.login(username=self.user_username, password=self.user_password)
        self.client.logout()
        last_non_hijack_login = User.objects.get(id=self.user.id).last_login
        self.assertIsNotNone(last_non_hijack_login)
        self.client.login(username=self.superuser_username, password=self.superuser_password)
        response = self._hijack(self.user.id)
        self.assertHijackSuccess(response)
        self._release_hijack()
        self.assertEqual(User.objects.get(id=self.user.id).last_login, last_non_hijack_login)

    def test_admin(self):
        ua = HijackUserAdmin(User, AdminSite())
        self.assertEqual(ua.list_display,
                         ('username', 'email', 'first_name', 'last_name',
                          'last_login', 'date_joined', 'is_staff',
                          'hijack_field', ))

    def test_disable_hijack_warning(self):
        response = self._hijack(self.user.id)
        self.assertTrue('hijacked-warning' in str(response.content))
        self.assertTrue(self.client.session['is_hijacked_user'])
        self.assertTrue(self.client.session['display_hijack_warning'])

        response = self.client.get('/hijack/disable-hijack-warning/?next=/hello/', follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse('hijacked-warning' in str(response.content))
        self.assertTrue(self.client.session['is_hijacked_user'])
        self.assertFalse(self.client.session['display_hijack_warning'])
        self._release_hijack()

    def test_permissions(self):
        self.assertTrue(self.superuser.is_superuser)
        self.assertTrue(self.superuser.is_staff)
        self.assertFalse(self.staff_user.is_superuser)
        self.assertTrue(self.staff_user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)

    def test_settings(self):
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_DISPLAY_ADMIN_BUTTON'))
        self.assertTrue(hijack_settings.HIJACK_DISPLAY_ADMIN_BUTTON)
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_DISPLAY_WARNING'))
        self.assertTrue(hijack_settings.HIJACK_DISPLAY_WARNING)
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_URL_ALLOWED_ATTRIBUTES'))
        self.assertEqual(hijack_settings.HIJACK_URL_ALLOWED_ATTRIBUTES, ('user_id', 'email', 'username'))
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_AUTHORIZE_STAFF'))
        self.assertFalse(hijack_settings.HIJACK_AUTHORIZE_STAFF)
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF'))
        self.assertFalse(hijack_settings.HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF)
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_LOGIN_REDIRECT_URL'))
        self.assertEqual(hijack_settings.HIJACK_LOGIN_REDIRECT_URL, '/hello/')
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_LOGOUT_REDIRECT_URL'))
        self.assertEqual(hijack_settings.HIJACK_LOGOUT_REDIRECT_URL, '/hello/')
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_AUTHORIZATION_CHECK'))
        self.assertEqual(hijack_settings.HIJACK_AUTHORIZATION_CHECK, 'hijack.helpers.is_authorized')
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_DECORATOR'))
        self.assertEqual(hijack_settings.HIJACK_DECORATOR, 'django.contrib.admin.views.decorators.staff_member_required')
        self.assertTrue(hasattr(hijack_settings, 'HIJACK_USE_BOOTSTRAP'))
        self.assertFalse(hijack_settings.HIJACK_USE_BOOTSTRAP)

    def test_settings_override(self):
        self.assertTrue(hijack_settings.HIJACK_DISPLAY_ADMIN_BUTTON)
        with SettingsOverride(hijack_settings, HIJACK_DISPLAY_ADMIN_BUTTON=False):
            self.assertFalse(hijack_settings.HIJACK_DISPLAY_ADMIN_BUTTON)
        self.assertTrue(hijack_settings.HIJACK_DISPLAY_ADMIN_BUTTON)

    def test_is_authorized(self):
        self.assertFalse(hijack_settings.HIJACK_AUTHORIZE_STAFF)
        self.assertFalse(hijack_settings.HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF)
        self.assertTrue(is_authorized(self.superuser, self.superuser))
        self.assertTrue(is_authorized(self.superuser, self.staff_user))
        self.assertTrue(is_authorized(self.superuser, self.user))
        self.assertFalse(is_authorized(self.staff_user, self.superuser))
        self.assertFalse(is_authorized(self.staff_user, self.staff_user))
        self.assertFalse(is_authorized(self.staff_user, self.user))
        self.assertFalse(is_authorized(self.user, self.superuser))
        self.assertFalse(is_authorized(self.user, self.staff_user))
        self.assertFalse(is_authorized(self.user, self.user))

    def test_is_authorized_staff_authorized(self):
        with SettingsOverride(hijack_settings, HIJACK_AUTHORIZE_STAFF=True):
            self.assertTrue(hijack_settings.HIJACK_AUTHORIZE_STAFF)
            self.assertFalse(hijack_settings.HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF)
            self.assertTrue(is_authorized(self.superuser, self.superuser))
            self.assertTrue(is_authorized(self.superuser, self.staff_user))
            self.assertTrue(is_authorized(self.superuser, self.user))
            self.assertFalse(is_authorized(self.staff_user, self.superuser))
            self.assertFalse(is_authorized(self.staff_user, self.staff_user))
            self.assertTrue(is_authorized(self.staff_user, self.user))
            self.assertFalse(is_authorized(self.user, self.superuser))
            self.assertFalse(is_authorized(self.user, self.staff_user))
            self.assertFalse(is_authorized(self.user, self.user))

    def test_is_authorized_staff_authorized_to_hijack_staff(self):
        with SettingsOverride(hijack_settings, HIJACK_AUTHORIZE_STAFF=True, HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF=True):
            self.assertTrue(hijack_settings.HIJACK_AUTHORIZE_STAFF)
            self.assertTrue(hijack_settings.HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF)
            self.assertTrue(is_authorized(self.superuser, self.superuser))
            self.assertTrue(is_authorized(self.superuser, self.staff_user))
            self.assertTrue(is_authorized(self.superuser, self.user))
            self.assertFalse(is_authorized(self.staff_user, self.superuser))
            self.assertTrue(is_authorized(self.staff_user, self.staff_user))
            self.assertTrue(is_authorized(self.staff_user, self.user))
            self.assertFalse(is_authorized(self.user, self.superuser))
            self.assertFalse(is_authorized(self.user, self.staff_user))
            self.assertFalse(is_authorized(self.user, self.user))

    def test_is_authorized_to_hijack_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        with SettingsOverride(hijack_settings, HIJACK_AUTHORIZE_STAFF=True, HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF=True):
            self.assertFalse(is_authorized(self.superuser, self.user))
            self.assertFalse(is_authorized(self.staff_user, self.user))
            self.assertFalse(is_authorized(self.user, self.user))

    def test_notification_tag(self):
        response = self._hijack(self.user.id)
        self.assertHijackSuccess(response)
        response = self.client.get('/hello/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('Notification tag' in str(response.content))
        self.assertTrue('hijacked-warning' in str(response.content))

    def test_notification_filter(self):
        response = self._hijack(self.user.id)
        self.assertHijackSuccess(response)
        response = self.client.get('/hello/filter/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('Notification filter' in str(response.content))
        self.assertTrue('hijacked-warning' in str(response.content))


if django.VERSION >= (1, 7):
    from django.core.checks import Error, Warning
    from hijack import checks
    from hijack.apps import HijackConfig


    class ChecksTests(TestCase):

        def test_check_url_allowed_attributes(self):
            errors = checks.check_url_allowed_attributes(HijackConfig)
            self.assertFalse(errors)

            with SettingsOverride(hijack_settings, HIJACK_URL_ALLOWED_ATTRIBUTES=('username',)):
                errors = checks.check_url_allowed_attributes(HijackConfig)
                self.assertFalse(errors)

            with SettingsOverride(hijack_settings, HIJACK_URL_ALLOWED_ATTRIBUTES=('username', 'email')):
                errors = checks.check_url_allowed_attributes(HijackConfig)
                self.assertFalse(errors)

            with SettingsOverride(hijack_settings, HIJACK_URL_ALLOWED_ATTRIBUTES=('other',)):
                errors = checks.check_url_allowed_attributes(HijackConfig)
                expected_errors = [
                    Error(
                        'Setting HIJACK_URL_ALLOWED_ATTRIBUTES needs to be '
                        'subset of (user_id, email, username)',
                        hint=None,
                        obj=hijack_settings.HIJACK_URL_ALLOWED_ATTRIBUTES,
                        id='hijack.E001',
                    )
                ]
                self.assertEqual(errors, expected_errors)

        def test_check_display_admin_button_with_custom_user_model(self):
            warnings = checks.check_display_admin_button_with_custom_user_model(HijackConfig)
            self.assertFalse(warnings)

            with SettingsOverride(hijack_settings, HIJACK_DISPLAY_ADMIN_BUTTON=False):
                warnings = checks.check_display_admin_button_with_custom_user_model(HijackConfig)
                self.assertFalse(warnings)

            with SettingsOverride(hijack_settings, HIJACK_DISPLAY_ADMIN_BUTTON=True):
                warnings = checks.check_display_admin_button_with_custom_user_model(HijackConfig)
                self.assertFalse(warnings)

        def test_check_legacy_settings(self):
            with SettingsOverride(settings, SHOW_HIJACKUSER_IN_ADMIN=False):
                warnings = checks.check_legacy_settings(HijackConfig)
                expected_warnings = [
                    Warning(
                        'Deprecation warning: Setting "SHOW_HIJACKUSER_IN_ADMIN" has been renamed to "HIJACK_DISPLAY_ADMIN_BUTTON"',
                        hint=None,
                        obj=None,
                        id='hijack.W002'
                    )
                ]
                self.assertEqual(warnings, expected_warnings)

        def test_check_staff_authorization_settings(self):
            errors = checks.check_staff_authorization_settings(HijackConfig)
            self.assertFalse(errors)
            with SettingsOverride(hijack_settings, HIJACK_AUTHORIZE_STAFF=True):
                errors = checks.check_staff_authorization_settings(HijackConfig)
                self.assertFalse(errors)
            with SettingsOverride(hijack_settings, HIJACK_AUTHORIZE_STAFF=True, HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF=True):
                errors = checks.check_staff_authorization_settings(HijackConfig)
                self.assertFalse(errors)
            with SettingsOverride(hijack_settings, HIJACK_AUTHORIZE_STAFF=False, HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF=True):
                errors = checks.check_staff_authorization_settings(HijackConfig)
                expected_errors = [
                    Error(
                        'Setting HIJACK_AUTHORIZE_STAFF_TO_HIJACK_STAFF may not be True if HIJACK_AUTHORIZE_STAFF is False.',
                        hint=None,
                        obj=None,
                        id='hijack.E004',
                    )
                ]
                self.assertEqual(errors, expected_errors)