import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';

export interface AnalysisResponse {
  resumen: string;
  implicaciones_legales: string[];
  fundamento_juridico: string[];
}

@Injectable({
  providedIn: 'root',
})
export class AnalysisService {
  private readonly http = inject(HttpClient);

  analyze(file: File): Observable<AnalysisResponse> {
    const formData = new FormData();
    formData.append('file', file);

    return this.http.post<AnalysisResponse>(
      `${environment.apiUrl}/analyze`,
      formData,
    );
  }
}
