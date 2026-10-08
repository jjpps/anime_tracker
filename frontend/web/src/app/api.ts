import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable } from 'rxjs';

/** Um anime iniciado com pelo menos uma novidade (termos no CONTEXT.md). */
export interface Novidade {
  series_id: string;
  title: string;
  /** Pôster vertical da CR; null até o próximo sync ou se a CR não tiver imagem. */
  poster: string | null;
  seasons_watched: number;
  last_watched_at: string | null;
  new_seasons: { title: string; episodes: number }[];
  continuation: { title: string; episodes: number } | null;
}

/** Anime que marquei para parar de acompanhar. */
export interface Largado {
  series_id: string;
  title: string;
  poster: string | null;
  dropped_at: string;
}

export interface EpisodioPendente {
  number: number;
  id: string | null;
  title: string | null;
}

/** Detalhe de um anime: CR sempre, AniList quando respondeu (docs/adr/0002). */
export interface AnimeDetalhe {
  series_id: string;
  title: string;
  poster: string | null;
  largado: boolean;
  anilist: {
    siteUrl: string;
    description: string | null;
    averageScore: number | null;
    genres: string[];
    status: string | null;
    episodes: number | null;
    seasonYear: number | null;
    bannerImage: string | null;
    title: { romaji: string | null; english: string | null };
  } | null;
  /** AniList fora do ar: diferente de "não achou", que vem com anilist null. */
  anilist_erro: boolean;
  pendentes: { title: string; episodes: EpisodioPendente[] }[];
}

export interface Stats {
  series: number;
  seasons: number;
  episodes: number;
  novidades: number;
  dropped: number;
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

  /** Contagens do menu; recarregadas depois de qualquer mudança nas listas. */
  stats = signal<Stats | null>(null);
  /** Sobe a cada sync concluído: as páginas recarregam a lista quando muda. */
  versao = signal(0);
  erro = signal<string | null>(null);

  recarregarStats() {
    this.http.get<Stats>('/api/stats').subscribe({
      next: (s) => this.stats.set(s),
      error: () => this.erro.set('não consegui falar com o servidor'),
    });
  }

  novidades(): Observable<Novidade[]> {
    return this.http.get<Novidade[]>('/api/novidades');
  }

  anime(seriesId: string): Observable<AnimeDetalhe> {
    return this.http.get<AnimeDetalhe>(`/api/anime/${encodeURIComponent(seriesId)}`);
  }

  largados(): Observable<Largado[]> {
    return this.http.get<Largado[]>('/api/largados');
  }

  pararDeAcompanhar(seriesId: string) {
    return this.http.put(`/api/largados/${encodeURIComponent(seriesId)}`, {});
  }

  voltarAAcompanhar(seriesId: string) {
    return this.http.delete(`/api/largados/${encodeURIComponent(seriesId)}`);
  }

  tarefa(): Observable<Tarefa> {
    return this.http.get<Tarefa>('/api/task');
  }

  baixarCrunchyroll(force = false) {
    return this.http.post<{ iniciado: boolean }>('/api/crunchyroll', { force });
  }
}
