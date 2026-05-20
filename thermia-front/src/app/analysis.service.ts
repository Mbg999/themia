import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';

export interface Fuente {
  law_id: string;
  law_title: string;
  article: string;
  section: string;
  hierarchy_path: string;
  legal_rank: string;
  status: string;
  jurisdiction: string;
  eli: string;
  title?: string;
  rank?: string;
  country?: string;
  source?: string;
  url?: string;
  url_eli?: string;
  [key: string]: unknown;
}

export interface AnalysisResponse {
  resumen: string;
  implicaciones_legales: string[];
  fundamento_juridico: string[];
  fuentes?: Fuente[];
}

@Injectable({
  providedIn: 'root',
})
export class AnalysisService {
  private readonly http = inject(HttpClient);

  analyze(file: File): Observable<AnalysisResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers = new HttpHeaders({
      Authorization: `Bearer ${environment.apiAuthToken}`,
    });

    return this.http.post<AnalysisResponse>(`${environment.apiUrl}/analyze`, formData, { headers });
  }
}
