import { describe, it, expect, vi, beforeEach } from 'vitest';
import { of } from 'rxjs';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { AnalysisResponse } from './analysis.service';

/**
 * Unit-test AnalysisService by constructing it in an Angular injection context
 * so that inject(HttpClient) is resolved by a mock we provide.
 */
import { runInInjectionContext, Injector } from '@angular/core';
import { AnalysisService } from './analysis.service';

function makeHttpClientMock(postFn: ReturnType<typeof vi.fn>) {
  return {
    post: postFn,
  } as unknown as HttpClient;
}

function buildService(httpMock: HttpClient): AnalysisService {
  const injector = Injector.create({
    providers: [
      { provide: AnalysisService, useClass: AnalysisService },
      { provide: HttpClient, useValue: httpMock },
    ],
  });
  return injector.get(AnalysisService);
}

describe('AnalysisService', () => {
  let postSpy: ReturnType<typeof vi.fn>;
  let service: AnalysisService;

  beforeEach(() => {
    postSpy = vi.fn();
    const httpMock = makeHttpClientMock(postSpy);
    service = buildService(httpMock);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should send POST to the /analyze endpoint', () => {
    const file = new File(['%PDF-content'], 'test.pdf', { type: 'application/pdf' });
    const mockResponse: AnalysisResponse = {
      resumen: 'Test summary',
      implicaciones_legales: ['Item 1'],
      fundamento_juridico: ['Art. 1'],
    };
    postSpy.mockReturnValue(of(mockResponse));

    let result: AnalysisResponse | undefined;
    service.analyze(file).subscribe((r) => (result = r));

    expect(postSpy).toHaveBeenCalledOnce();
    const [url] = postSpy.mock.calls[0];
    expect(url).toMatch(/\/analyze$/);
    expect(result).toEqual(mockResponse);
  });

  it('should set Authorization header with Bearer token', () => {
    const file = new File(['%PDF-content'], 'test.pdf', { type: 'application/pdf' });
    postSpy.mockReturnValue(of({ resumen: '', implicaciones_legales: [], fundamento_juridico: [] }));

    service.analyze(file).subscribe();

    const [, , options] = postSpy.mock.calls[0] as [string, FormData, { headers: HttpHeaders }];
    expect(options.headers.get('Authorization')).toMatch(/^Bearer /);
  });

  it('should send file as FormData field named "file"', () => {
    const file = new File(['%PDF-content'], 'contract.pdf', { type: 'application/pdf' });
    postSpy.mockReturnValue(of({ resumen: '', implicaciones_legales: [], fundamento_juridico: [] }));

    service.analyze(file).subscribe();

    const [, body] = postSpy.mock.calls[0] as [string, FormData];
    expect(body instanceof FormData).toBe(true);
    expect(body.get('file')).toBe(file);
  });

  it('should return typed Observable<AnalysisResponse>', () => {
    const file = new File(['%PDF-content'], 'test.pdf', { type: 'application/pdf' });
    const expected: AnalysisResponse = {
      resumen: 'Legal document summary',
      implicaciones_legales: ['Clause A', 'Clause B'],
      fundamento_juridico: ['Art. 1823 CC'],
    };
    postSpy.mockReturnValue(of(expected));

    let result: AnalysisResponse | undefined;
    service.analyze(file).subscribe((r) => (result = r));

    expect(result).toEqual(expected);
    expect(result?.resumen).toBe('Legal document summary');
    expect(result?.implicaciones_legales.length).toBe(2);
    expect(result?.fundamento_juridico.length).toBe(1);
  });
});
