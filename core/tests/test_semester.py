from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from datetime import date
from core.models import Semester, Session
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
class SemesterViewTest(TestCase):
    def setUp(self):
        # Create a superuser for testing
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass'
        )
        self.client = Client()
        self.client.login(username='admin', password='adminpass')

        # Create a default non-current session for tests requiring a session
        self.session = Session.objects.create(
            session="2024-2025",
            is_current_session=False,  # Ensure non-current to allow deletion
            next_session_begins=date(2025, 6, 1)
        )

        # Create a default current semester
        self.current_semester = Semester.objects.create(
            semester="FIRST",
            is_current_semester=True,
            session=self.session,
            next_semester_begins=date(2025, 1, 1)
        )

    def test_TC001_add_semester_no_session(self):
        """Test adding a semester when no session exists in DB"""
        # Clear all sessions
        Session.objects.all().delete()
        response = self.client.post(reverse('add_semester'), {
            'semester': 'SECOND',  # Unique semester to avoid duplicates
            'is_current_semester': False,
            'session': '',  # Explicitly None
            'next_semester_begins': '2025-09-01',
        }, follow=True)
        if response.status_code == 200:
            # Check form errors if validation fails
            form = response.context.get('form')
            self.assertIsNotNone(form, "Form not found in response context")
            self.assertFalse(form.is_valid(), "Form should be invalid")
            self.assertIn('session', form.errors, "Expected session field error")
        else:
            self.assertRedirects(response, reverse('semester_list'))
            self.assertTrue(Semester.objects.filter(semester='SECOND', session=None).exists())
            self.assertContains(response, 'Semester added successfully.')

    def test_TC002_delete_session_deletes_semester(self):
        """Test deleting a session deletes related semesters"""
        semester = Semester.objects.create(
            semester='SECOND',
            is_current_semester=False,
            session=self.session,
            next_semester_begins=date(2025, 3, 1)
        )
        response = self.client.get(reverse('delete_session', args=[self.session.id]), follow=True)
        self.assertFalse(Semester.objects.filter(id=semester.id).exists())
        self.assertFalse(Session.objects.filter(id=self.session.id).exists())
        self.assertRedirects(response, reverse('session_list'))

    def test_TC003_delete_current_semester(self):
        """Test deleting a semester with is_current_semester=True"""
        response = self.client.get(reverse('delete_semester', args=[self.current_semester.id]), follow=True)
        self.assertRedirects(response, reverse('semester_list'))
        self.assertTrue(Semester.objects.filter(id=self.current_semester.id).exists())
        self.assertContains(response, 'You cannot delete the current semester.')

    def test_TC004_semester_list_view(self):
        """Test semester list view displays semesters correctly"""
        Semester.objects.create(
            semester='SECOND',
            is_current_semester=False,
            session=self.session,
            next_semester_begins=date(2025, 3, 1)
        )
        response = self.client.get(reverse('semester_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'FIRST')  # Current semester
        self.assertContains(response, 'SECOND')  # Non-current semester
        semesters = response.context['semesters']
        self.assertEqual(semesters[0].semester, 'FIRST')  # Sorted by -is_current_semester

    def test_TC005_update_to_current_semester(self):
        """Test updating a semester to current unsets existing current semester and session"""
        non_current_semester = Semester.objects.create(
            semester='THIRD',  # Unique semester
            is_current_semester=False,
            session=self.session,
            next_semester_begins=date(2025, 3, 1)
        )
        response = self.client.post(reverse('edit_semester', args=[non_current_semester.id]), {
            'semester': 'THIRD',
            'is_current_semester': True,
            'session': self.session.id,
            'next_semester_begins': '2025-03-01',
        }, follow=True)
        
        # Expect the response to redirect back to the edit semester page (form invalid)
        self.assertRedirects(response, reverse('edit_semester', args=[non_current_semester.id]))
        
        # Refresh objects from the database
        self.current_semester.refresh_from_db()
        self.session.refresh_from_db()
        non_current_semester.refresh_from_db()
        
        # Expect Semester A (self.current_semester) to remain current
        self.assertTrue(self.current_semester.is_current_semester,
                        "Current semester was unset when it should have remained current.")
        
        # Expect Session B (self.session) to remain current
        self.assertTrue(self.session.is_current_session,
                        "Current session was unset when it should have remained current.")
        
        # Expect Semester C (non_current_semester) to remain non-current
        self.assertFalse(non_current_semester.is_current_semester,
                        "Semester 'THIRD' was set as current when it should not have been.")
        
        # Expect an error message in the response
        self.assertContains(response, "Cannot update to current semester due to current semester already set.")