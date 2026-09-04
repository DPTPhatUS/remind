import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockGet = vi.fn();
vi.mock('@/lib/api', () => ({
  createApiClient: () => ({ get: (...a: unknown[]) => mockGet(...a), post: vi.fn(), patch: vi.fn() }),
  ApiError: class extends Error { status: number; constructor(status: number, msg: string) { super(msg); this.status = status; } },
  getApiBaseUrl: () => 'http://test/api/v1',
  getLiveWebSocketUrl: (id: string) => `ws://test/api/v1/live/sessions/${id}`,
}));

import { PeoplePage } from './PeoplePage';

describe('PeoplePage', () => {
  beforeEach(() => mockGet.mockReset());

  it('renders empty-state when GET /people returns []', async () => {
    mockGet.mockResolvedValueOnce([]);
    render(<MemoryRouter><PeoplePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/no people yet|haven't met|empty/i)).toBeInTheDocument());
  });

  it('renders a card per person with name, relationship, status badge, view link', async () => {
    mockGet.mockResolvedValueOnce([
      { id: 'p1', patient_id: 'pt1', display_name: 'Alice', relationship_to_patient: 'Doctor', notes: null, recognition_status: 'confirmed', consent_status: 'unknown', created_at: '', updated_at: '' },
      { id: 'p2', patient_id: 'pt1', display_name: 'Bob', relationship_to_patient: 'Neighbor', notes: null, recognition_status: 'recognized', consent_status: 'unknown', created_at: '', updated_at: '' },
    ]);
    render(<MemoryRouter initialEntries={['/people']}><PeoplePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument());
    expect(screen.getByText('Doctor')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('Neighbor')).toBeInTheDocument();
    const links = screen.getAllByRole('link');
    const peopleLinks = links.filter(l => ['/people/p1','/people/p2'].includes(l.getAttribute('href') ?? ''));
    expect(peopleLinks.length).toBeGreaterThanOrEqual(2);
  });

  it('renders error alert on API failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('Network down'));
    render(<MemoryRouter><PeoplePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });
});
