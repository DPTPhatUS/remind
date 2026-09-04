import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const mockGet = vi.fn();
const mockPatch = vi.fn();
vi.mock('@/lib/api', () => ({
  createApiClient: () => ({ get: (...a: unknown[]) => mockGet(...a), post: vi.fn(), patch: (...a: unknown[]) => mockPatch(...a) }),
  ApiError: class extends Error { status: number; constructor(status: number, msg: string) { super(msg); this.status = status; } },
  getApiBaseUrl: () => 'http://test/api/v1',
  getLiveWebSocketUrl: (id: string) => `ws://test/api/v1/live/sessions/${id}`,
}));

const toastSpy = vi.fn();
vi.mock('sonner', () => ({
  toast: { success: (...a: unknown[]) => toastSpy('success', ...a), error: (...a: unknown[]) => toastSpy('error', ...a) },
}));

import { ProfilePage } from './ProfilePage';

const PATIENT = {
  id: 'pt1', display_name: 'Patient', date_of_birth: '1955-04-12',
  preferences: { theme: 'light' }, accessibility_settings: { font_size: 'lg' },
  created_at: '2026-01-01', updated_at: '2026-01-01',
};

describe('ProfilePage', () => {
  beforeEach(() => { mockGet.mockReset(); mockPatch.mockReset(); toastSpy.mockReset(); });

  it('pre-fills the form with patient values', async () => {
    mockGet.mockResolvedValueOnce(PATIENT);
    render(<MemoryRouter><ProfilePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByDisplayValue('Patient')).toBeInTheDocument());
    expect(screen.getByDisplayValue('1955-04-12')).toBeInTheDocument();
  });

  it('submits PATCH /patients/me on save with success toast', async () => {
    mockGet.mockResolvedValueOnce(PATIENT);
    mockPatch.mockResolvedValueOnce({ ...PATIENT, display_name: 'New Name' });
    render(<MemoryRouter><ProfilePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByDisplayValue('Patient')).toBeInTheDocument());
    const input = screen.getByLabelText(/name|display name/i);
    await userEvent.clear(input);
    await userEvent.type(input, 'New Name');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/patients/me', expect.objectContaining({ display_name: 'New Name' })));
    expect(toastSpy).toHaveBeenCalledWith('success', expect.any(String));
  });

  it('blocks save when display_name is empty (inline error, no PATCH)', async () => {
    mockGet.mockResolvedValueOnce(PATIENT);
    render(<MemoryRouter><ProfilePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByDisplayValue('Patient')).toBeInTheDocument());
    const input = screen.getByLabelText(/name|display name/i);
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await new Promise(r => setTimeout(r, 50));
    expect(mockPatch).not.toHaveBeenCalled();
    expect(screen.getByText(/name.*required|please enter|name is required/i)).toBeInTheDocument();
  });
});
