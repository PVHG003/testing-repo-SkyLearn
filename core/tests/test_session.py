from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from datetime import date
from core.models import Session
from django.test.utils import override_settings
from django.conf import settings

User = get_user_model()

# Disable translation and whitenoise middleware, and use basic staticfiles storage during tests
@override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
    MIDDLEWARE=[
        m for m in settings.MIDDLEWARE 
        if m not in ['django.middleware.locale.LocaleMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware']
    ],
    LANGUAGE_CODE='en-us'
)
class SessionViewTest(TestCase):
    def setUp(self):
        # Create a superuser for testing
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass'
        )
        self.client = Client()
        self.client.login(username='admin', password='adminpass')

        # Create a default current session
        self.current_session = Session.objects.create(
            session="2024-2025",
            is_current_session=True,
            next_session_begins=date(2025, 1, 1)
        )

    def test_TC001_session_name_too_long(self):
        """Test session name exceeding 200 characters"""
        long_name = "A" * 201
        response = self.client.post(reverse('add_session'), {
            'session': long_name,
            'is_current_session': False,
            'next_session_begins': '2026-01-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'session', 'Ensure this value has at most 200 characters (it has 201).')
        self.assertFalse(Session.objects.filter(session=long_name).exists())

    def test_TC002_set_new_current_session(self):
        """Test creating a new current session unsets existing current session"""
        response = self.client.post(reverse('add_session'), {
            'session': '2025-2026',
            'is_current_session': True,
            'next_session_begins': '2026-01-01',
        }, follow=True)
        self.assertRedirects(response, reverse('session_list'))
        self.current_session.refresh_from_db()
        new_session = Session.objects.get(session='2025-2026')
        self.assertFalse(self.current_session.is_current_session)
        self.assertTrue(new_session.is_current_session)
        self.assertContains(response, 'Session added successfully')

    def test_TC003_invalid_date_format(self):
        """Test invalid date format for next_session_begins"""
        response = self.client.post(reverse('add_session'), {
            'session': '2025-2026',
            'is_current_session': False,
            'next_session_begins': '2025/01/01',
        })
        self.assertEqual(response.status_code, 200)
        # Expecting 'Enter a valid date/time.' due to SessionForm; bug: should be 'Enter a valid date.' (model uses DateField)
        self.assertFormError(response, 'form', 'next_session_begins', 'Enter a valid date/time.')
        self.assertFalse(Session.objects.filter(session='2025-2026').exists())

    def test_TC004_date_too_old(self):
        """Test next_session_begins in distant past"""
        response = self.client.post(reverse('add_session'), {
            'session': '2025-2026',
            'is_current_session': False,
            'next_session_begins': '1900-01-01',
        }, follow=True)
        
        # Expect the session to NOT be created
        self.assertFalse(Session.objects.filter(session='2025-2026').exists(), 
                        "Session '2025-2026' was created when it should not have been.")
        
        # Expect the response to redirect back to the add session page (form invalid)
        self.assertRedirects(response, reverse('add_session'))
        
        # Expect an error message in the response
        self.assertContains(response, "Date too far from present.")

    def test_TC005_special_characters_in_name(self):
        """Test session name with special characters and emoji"""
        response = self.client.post(reverse('add_session'), {
            'session': '🎓@SkyLearn2025',
            'is_current_session': False,
            'next_session_begins': '2026-01-01',
        }, follow=True)
        
        # Expect the session to NOT be created
        self.assertFalse(Session.objects.filter(session='🎓@SkyLearn2025').exists(),
                        "Session '🎓@SkyLearn2025' was created when it should not have been.")
        
        # Expect the response to redirect back to the add session page (form invalid)
        self.assertRedirects(response, reverse('add_session'))
        
        # Expect an error message in the response
        self.assertContains(response, "Invalid session name.")

    def test_TC006_session_list_view(self):
        """Test session list view displays sessions correctly"""
        Session.objects.create(session='2023-2024', is_current_session=False)
        response = self.client.get(reverse('session_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2024-2025')  # Current session
        self.assertContains(response, '2023-2024')  # Non-current session
        sessions = response.context['sessions']
        self.assertEqual(sessions[0].session, '2024-2025')  # Sorted by -is_current_session

    def test_TC007_delete_non_current_session(self):
        """Test deleting a non-current session"""
        non_current = Session.objects.create(
            session='2023-2024',
            is_current_session=False,
            next_session_begins=date(2024, 1, 1)
        )
        response = self.client.get(reverse('delete_session', args=[non_current.id]), follow=True)
        self.assertRedirects(response, reverse('session_list'))
        self.assertFalse(Session.objects.filter(id=non_current.id).exists())
        self.assertContains(response, 'Session successfully deleted')

    def test_TC008_delete_current_session(self):
        """Test attempting to delete the current session"""
        response = self.client.get(reverse('delete_session', args=[self.current_session.id]), follow=True)
        self.assertRedirects(response, reverse('session_list'))
        self.assertTrue(Session.objects.filter(id=self.current_session.id).exists())
        self.assertContains(response, 'You cannot delete the current session')

    def test_TC009_update_to_current_session(self):
        """Test updating a session to current unsets existing current session"""
        non_current = Session.objects.create(
            session='2023-2024',
            is_current_session=False,
            next_session_begins=date(2024, 1, 1)
        )
        response = self.client.post(reverse('edit_session', args=[non_current.id]), {
            'session': '2023-2024',
            'is_current_session': True,
            'next_session_begins': '2024-01-01',
        }, follow=True)
        
        # Expect the response to redirect back to the edit session page (form invalid)
        self.assertRedirects(response, reverse('edit_session', args=[non_current.id]))
        
        # Refresh session objects from the database
        self.current_session.refresh_from_db()
        non_current.refresh_from_db()
        
        # Expect Session A (self.current_session) to remain current
        self.assertTrue(self.current_session.is_current_session,
                        "Current session was unset when it should have remained current.")
        
        # Expect Session B (non_current) to remain non-current
        self.assertFalse(non_current.is_current_session,
                        "Session '2023-2024' was set as current when it should not have been.")
        
        # Expect an error message in the response
        self.assertContains(response, "Current session is already set.")

    def test_TC010_add_valid_session(self):
        """Test adding a valid session"""
        response = self.client.post(reverse('add_session'), {
            'session': '2026-2027',
            'is_current_session': False,
            'next_session_begins': '2027-01-01',
        }, follow=True)
        self.assertRedirects(response, reverse('session_list'))
        self.assertTrue(Session.objects.filter(session='2026-2027').exists())
        self.assertContains(response, 'Session added successfully')

    def test_TC011_update_session_name(self):
        """Test updating session name"""
        response = self.client.post(reverse('edit_session', args=[self.current_session.id]), {
            'session': 'Updated 2024-2025',
            'is_current_session': True,
            'next_session_begins': '2025-01-01',
        }, follow=True)
        self.assertRedirects(response, reverse('session_list'))
        self.current_session.refresh_from_db()
        self.assertEqual(self.current_session.session, 'Updated 2024-2025')
        self.assertContains(response, 'Session updated successfully')

    def test_TC012_add_duplicate_session_name(self):
        """Test adding a session with a duplicate name"""
        response = self.client.post(reverse('add_session'), {
            'session': '2024-2025',  # Matches existing session
            'is_current_session': False,
            'next_session_begins': '2026-01-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'session', 'Session with this Session already exists.')
        self.assertEqual(Session.objects.filter(session='2024-2025').count(), 1)

    def test_TC013_empty_session_name(self):
        """Test adding a session with an empty name"""
        response = self.client.post(reverse('add_session'), {
            'session': '',
            'is_current_session': False,
            'next_session_begins': '2026-01-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'session', 'This field is required.')
        self.assertFalse(Session.objects.filter(session='').exists())

    def test_TC014_next_session_begins_today(self):
        """Test next_session_begins set to current date"""
        today = date.today()
        response = self.client.post(reverse('add_session'), {
            'session': '2025-2026',
            'is_current_session': False,
            'next_session_begins': today.strftime('%Y-%m-%d'),
        }, follow=True)
        self.assertRedirects(response, reverse('session_list'))
        # Note: Model accepts today's date; recommend validation if future date is required
        self.assertTrue(Session.objects.filter(session='2025-2026').exists())

#python manage.py test core.tests.test_session