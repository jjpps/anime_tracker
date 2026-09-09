import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export type Provider = 'anilist' | 'mal';

/** Uma temporada da Crunchyroll com o vínculo que já tem. */
export interface ItemBiblioteca {
  season_id: string;
  series_id: string;
  series_title: string;
  season_number: number;
  cr_episodes: number;
  anilist_id: number | null;
  anilist_title: string | null;
  anilist_url: string | null;
  mal_id: number | null;
  mal_title: string | null;
  confidence: number;
  review_status: 'pending' | 'confirmed' | 'rejected';
  /** 'anilist', 'mal' ou 'anilist,mal' — de quais provedores veio o vínculo. */
  providers: string;
}

export interface Correcao extends ItemBiblioteca {
  duplicate_of: number | null;
  season_title: string | null;
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
}

export interface Stats {
  series: number;
  seasons: number;
  episodes: number;
  matched: number;
  pending: number;
  confirmed: number;
  rejected: number;
  com_mal_id: number;
  mal_conferidos: number;
  catalogo_local: boolean;
  anilist_conectado: boolean;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  stats(): Observable<Stats> {
    return this.http.get<Stats>('/api/stats');
  }

  biblioteca(q = ''): Observable<ItemBiblioteca[]> {
    return this.http.get<ItemBiblioteca[]>('/api/library', { params: { q } });
  }

  correcoes(provider?: Provider, q = ''): Observable<Correcao[]> {
    const params: Record<string, string> = { q };
    if (provider) params['provider'] = provider;
    return this.http.get<Correcao[]>('/api/corrections', { params });
  }

  tarefa(): Observable<Tarefa> {
    return this.http.get<Tarefa>('/api/task');
  }

  baixarCrunchyroll(force = false) {
    return this.http.post<{ iniciado: boolean }>('/api/crunchyroll', { force });
  }

  sincronizarProvedor(provider: Provider) {
    return this.http.post<{ iniciado: boolean }>(`/api/provider/${provider}`, {});
  }

  revisar(seasonId: string, status: string, anilistId?: number) {
    const corpo: Record<string, unknown> = { status };
    if (anilistId) corpo['anilist_id'] = anilistId;
    return this.http.post(`/api/review/${encodeURIComponent(seasonId)}`, corpo);
  }
}
