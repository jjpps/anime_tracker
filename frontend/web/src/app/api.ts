import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/** Um anime iniciado com pelo menos uma novidade (termos no CONTEXT.md). */
export interface Novidade {
  series_id: string;
  title: string;
  seasons_watched: number;
  last_watched_at: string | null;
  new_seasons: { title: string; episodes: number }[];
  continuation: { title: string; episodes: number } | null;
}

export interface Tarefa {
  rodando: boolean;
  tipo: string | null;
  etapa: string;
  feito: number;
  total: number;
  erro: string | null;
  resultado: Record<string, any> | null;
  minutos_ate_liberar: number;
  ultimo_sync: string | null;
  /** Falha do último sync, inclusive o do cron; some quando um sync dá certo. */
  erro_sync: string | null;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  novidades(): Observable<Novidade[]> {
    return this.http.get<Novidade[]>('/api/novidades');
  }

  tarefa(): Observable<Tarefa> {
    return this.http.get<Tarefa>('/api/task');
  }

  baixarCrunchyroll(force = false) {
    return this.http.post<{ iniciado: boolean }>('/api/crunchyroll', { force });
  }
}
