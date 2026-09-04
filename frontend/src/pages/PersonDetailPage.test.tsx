import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

// jsdom lacks PointerCapture APIs that Radix Select probes on open
if (typeof Element.prototype.hasPointerCapture !== 'function') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Element.prototype as any).hasPointerCapture = () => false;
}
if (typeof Element.prototype.setPointerCapture !== 'function') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Element.prototype as any).setPointerCapture = () => {};
}
if (typeof Element.prototype.releasePointerCapture !== 'function') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Element.prototype as any).releasePointerCapture = () => {};
}
if (typeof Element.prototype.scrollIntoView !== 'function') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Element.prototype as any).scrollIntoView = () => {};
}

const mockGet = vi.fn();
const mockPatch = vi.fn();
vi.mock('@/lib/api', () => ({
  createApiClient: () => ({ get: (...a: unknown[]) => mockGet(...a), post: vi.fn(), patch: (...a: unknown[]) => mockPatch(...a) }),
  ApiError: class extends Error { status: number; constructor(status: number, msg: string) { super(msg); this.status = status; } },
  getApiBaseUrl: () => 'http://test/api/v1',
  getLiveWebSocketUrl: (id: string) => `ws://test/api/v1/live/sessions/${id}`,
}));

import { PersonDetailPage } from './PersonDetailPage';

const KNOWN_ID = 'p-known';
const PERSON = {
  id: KNOWN_ID, patient_id: 'pt1', display_name: 'Alice', relationship_to_patient: 'Doctor',
  notes: 'Cardiologist', recognition_status: 'confirmed', consent_status: 'unknown',
  created_at: '2026-01-01', updated_at: '2026-01-01',
};

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/people/${id}`]}>
      <Routes><Route path="/people/:id" element={<PersonDetailPage />} /></Routes>
    </MemoryRouter>
  );
}

describe('PersonDetailPage', () => {
  beforeEach(() => { mockGet.mockReset(); mockPatch.mockReset(); });

  it('renders profile section for matching person', async () => {
    mockGet.mockImplementation(async (p: string) => p === '/people' ? [PERSON] : []);
    renderAt(KNOWN_ID);
    await waitFor(() => expect(screen.getByDisplayValue('Alice')).toBeInTheDocument());
    expect(screen.getByDisplayValue('Doctor')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Cardiologist')).toBeInTheDocument();
  });

  it('shows empty-state when id not in list', async () => {
    mockGet.mockImplementation(async (p: string) => p === '/people' ? [PERSON] : []);
    renderAt('unknown-id');
    await waitFor(() => expect(screen.getByText(/person not found|not found/i)).toBeInTheDocument());
  });

  it('PATCHes PATCH /people/:id on save', async () => {
    mockGet.mockImplementation(async (p: string) => p === '/people' ? [PERSON] : []);
    mockPatch.mockResolvedValueOnce({ ...PERSON, display_name: 'Alice Updated' });
    renderAt(KNOWN_ID);
    await waitFor(() => expect(screen.getByDisplayValue('Alice')).toBeInTheDocument());
    const input = screen.getByDisplayValue('Alice');
    await userEvent.clear(input);
    await userEvent.type(input, 'Alice Updated');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(`/people/${KNOWN_ID}`, expect.objectContaining({ display_name: 'Alice Updated' })));
  });

  it('recognition_status select offers only 4 values', async () => {
    mockGet.mockImplementation(async (p: string) => p === '/people' ? [PERSON] : []);
    renderAt(KNOWN_ID);
    await waitFor(() => expect(screen.getByDisplayValue('Alice')).toBeInTheDocument());
    // click Edit to enter edit mode
    await userEvent.click(screen.getByRole('button', { name: /edit/i }));
    const trigger = screen.getByRole('combobox');
    await userEvent.click(trigger);
    await waitFor(() => {
      for (const v of ['unknown','recognized','introduced','confirmed']) {
        expect(screen.getByRole('option', { name: new RegExp(v, 'i') })).toBeInTheDocument();
      }
      expect(screen.queryByRole('option', { name: /trusted/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('option', { name: /opted_out/i })).not.toBeInTheDocument();
    });
  });
});
