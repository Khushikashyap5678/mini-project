document.querySelectorAll('.dismiss').forEach(button => {
  button.addEventListener('click', () => {
    document.getElementById('main').focus({ preventScroll: true });
    button.closest('.flash').remove();
  });
});

const cancelDialog = document.getElementById('cancel-dialog');
if (cancelDialog && typeof cancelDialog.showModal === 'function') {
  let selectedForm = null;
  let opener = null;
  const keepButton = document.getElementById('keep-booking');
  document.querySelectorAll('.cancel-form').forEach(form => {
    form.addEventListener('submit', event => {
      event.preventDefault();
      selectedForm = form;
      opener = event.submitter;
      document.getElementById('cancel-description').textContent =
        `“${form.dataset.appointment}” will move to your cancelled bookings.`;
      cancelDialog.showModal();
      keepButton.focus();
    });
  });
  keepButton.addEventListener('click', () => cancelDialog.close());
  document.getElementById('confirm-cancel').addEventListener('click', () => selectedForm?.submit());
  cancelDialog.addEventListener('close', () => {
    opener?.focus();
    selectedForm = null;
  });
}

const bookingForm = document.querySelector('.booking-form');
if (bookingForm) {
  const department = document.getElementById('department');
  const date = document.getElementById('booking-date');
  const formatter = new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata',
  });

  function updatePreview() {
    const selectedReminder = bookingForm.querySelector('[name="reminder_minutes"]:checked');
    const value = date.value ? new Date(`${date.value}:00+05:30`) : null;
    document.getElementById('preview-department').textContent = department.selectedOptions[0]?.textContent;
    document.getElementById('preview-date').textContent =
      value && !Number.isNaN(value.getTime()) ? `${formatter.format(value)} IST` : 'Choose a date and time';
    document.getElementById('preview-reminder').textContent =
      selectedReminder?.closest('label').innerText.trim() || 'Choose a reminder';
  }

  bookingForm.addEventListener('input', updatePreview);
  bookingForm.addEventListener('change', updatePreview);
  updatePreview();
}
