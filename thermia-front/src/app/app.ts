import { Component, signal, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { AnalysisService, AnalysisResponse } from './analysis.service';

@Component({
  selector: 'app-root',
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly analysisService: AnalysisService;

  readonly selectedFile = signal<File | null>(null);
  readonly isLoading = signal(false);
  readonly result = signal<AnalysisResponse | null>(null);
  readonly error = signal<string | null>(null);

  constructor(analysisService?: AnalysisService) {
    this.analysisService = analysisService ?? inject(AnalysisService);
  }

  isAnalyzeEnabled(): boolean {
    return this.selectedFile() !== null && !this.isLoading();
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;

    if (file && file.type === 'application/pdf') {
      this.selectedFile.set(file);
      this.result.set(null);
      this.error.set(null);
    } else {
      this.selectedFile.set(null);
    }
  }

  onAnalyze(): void {
    const file = this.selectedFile();
    if (!file || this.isLoading()) {
      return;
    }

    this.isLoading.set(true);
    this.result.set(null);
    this.error.set(null);

    this.analysisService.analyze(file).subscribe({
      next: (response) => {
        this.result.set(response);
        this.isLoading.set(false);
      },
      error: (err: HttpErrorResponse) => {
        this.error.set(this.mapError(err));
        this.isLoading.set(false);
      },
    });
  }

  private mapError(err: HttpErrorResponse): string {
    if (err.status === 401) {
      return 'Clave de API incorrecta o no configurada.';
    }
    if (err.status === 422) {
      return 'El documento no contiene contenido legal reconocible.';
    }
    if (err.status === 503 || err.status === 0) {
      return 'El servicio no está disponible. Inténtelo de nuevo más tarde.';
    }
    return 'Ha ocurrido un error inesperado.';
  }
}
