import { describe, it, expect, beforeEach, vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { App } from './app';
import { AnalysisService } from './analysis.service';

function makeService(overrides: Partial<AnalysisService> = {}): AnalysisService {
  return {
    analyze: vi.fn(),
    ...overrides,
  } as unknown as AnalysisService;
}

describe('App component logic', () => {
  let comp: App;
  let svc: AnalysisService;

  beforeEach(() => {
    svc = makeService();
    comp = new App(svc);
  });

  // ---------------------------------------------------------------------------
  // File selection
  // ---------------------------------------------------------------------------

  it('button stays disabled when no file is selected', () => {
    expect(comp.isAnalyzeEnabled()).toBe(false);
  });

  it('selecting a non-PDF file keeps button disabled and shows error', () => {
    const file = new File(['data'], 'doc.docx', { type: 'application/msword' });
    const event = { target: { files: [file] } } as unknown as Event;
    comp.onFileChange(event);
    expect(comp.isAnalyzeEnabled()).toBe(false);
    expect(comp.error()).toBe('Solo se aceptan archivos PDF.');
  });

  it('selecting a .pdf file enables the Analizar button', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    const event = { target: { files: [file] } } as unknown as Event;
    comp.onFileChange(event);
    expect(comp.isAnalyzeEnabled()).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  it('button is disabled while request is in flight', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    const event = { target: { files: [file] } } as unknown as Event;
    comp.onFileChange(event);

    // analyze() returns an observable that never completes (simulates in-flight)
    vi.mocked(svc.analyze).mockReturnValue(
      new (require('rxjs').Observable)(() => {})
    );

    comp.onAnalyze();
    expect(comp.isLoading()).toBe(true);
    expect(comp.isAnalyzeEnabled()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Result state
  // ---------------------------------------------------------------------------

  it('renders result data after successful response', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    const event = { target: { files: [file] } } as unknown as Event;
    comp.onFileChange(event);

    const mockResponse = {
      resumen: 'Resumen del contrato',
      implicaciones_legales: ['Cláusula 1', 'Cláusula 2'],
      fundamento_juridico: ['Art. 1 CC'],
    };
    vi.mocked(svc.analyze).mockReturnValue(of(mockResponse));

    comp.onAnalyze();

    expect(comp.result()).toEqual(mockResponse);
    expect(comp.isLoading()).toBe(false);
    expect(comp.error()).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Error states
  // ---------------------------------------------------------------------------

  it('shows 401 error message and re-enables button', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    comp.onFileChange({ target: { files: [file] } } as unknown as Event);

    const err = new HttpErrorResponse({ status: 401, statusText: 'Unauthorized' });
    vi.mocked(svc.analyze).mockReturnValue(throwError(() => err));

    comp.onAnalyze();

    expect(comp.error()).toBe('Clave de API incorrecta o no configurada.');
    expect(comp.isLoading()).toBe(false);
    expect(comp.isAnalyzeEnabled()).toBe(true);
  });

  it('shows 422 error message', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    comp.onFileChange({ target: { files: [file] } } as unknown as Event);

    const err = new HttpErrorResponse({ status: 422, statusText: 'Unprocessable Entity' });
    vi.mocked(svc.analyze).mockReturnValue(throwError(() => err));

    comp.onAnalyze();

    expect(comp.error()).toBe('El documento no contiene contenido legal reconocible.');
  });

  it('shows 503 error message', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    comp.onFileChange({ target: { files: [file] } } as unknown as Event);

    const err = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    vi.mocked(svc.analyze).mockReturnValue(throwError(() => err));

    comp.onAnalyze();

    expect(comp.error()).toBe('El servicio no está disponible. Inténtelo de nuevo más tarde.');
  });

  it('shows network error (status 0) message', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    comp.onFileChange({ target: { files: [file] } } as unknown as Event);

    const err = new HttpErrorResponse({ status: 0, statusText: 'Unknown Error' });
    vi.mocked(svc.analyze).mockReturnValue(throwError(() => err));

    comp.onAnalyze();

    expect(comp.error()).toBe('El servicio no está disponible. Inténtelo de nuevo más tarde.');
  });

  it('shows generic error message for unexpected status codes', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    comp.onFileChange({ target: { files: [file] } } as unknown as Event);

    const err = new HttpErrorResponse({ status: 500, statusText: 'Internal Server Error' });
    vi.mocked(svc.analyze).mockReturnValue(throwError(() => err));

    comp.onAnalyze();

    expect(comp.error()).toBe('Ha ocurrido un error inesperado.');
  });

  it('all three result sections are accessible after success', () => {
    const file = new File(['%PDF'], 'contract.pdf', { type: 'application/pdf' });
    comp.onFileChange({ target: { files: [file] } } as unknown as Event);

    const mockResponse = {
      resumen: 'Un resumen completo',
      implicaciones_legales: ['Implicación A', 'Implicación B', 'Implicación C'],
      fundamento_juridico: ['Art. 1823 del Código Civil', 'Art. 45 LOPD'],
    };
    vi.mocked(svc.analyze).mockReturnValue(of(mockResponse));

    comp.onAnalyze();

    expect(comp.result()?.resumen).toBe('Un resumen completo');
    expect(comp.result()?.implicaciones_legales.length).toBe(3);
    expect(comp.result()?.fundamento_juridico.length).toBe(2);
  });
});
