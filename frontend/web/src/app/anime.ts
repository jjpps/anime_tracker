import { Component, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, AnimeDetalhe } from './api';

const CR = 'https://www.crunchyroll.com';

@Component({
  selector: 'app-anime',
  standalone: true,
  imports: [RouterLink],
  template: `
    <a routerLink="/" class="small">← voltar</a>

    @if (carregando()) {
      <p class="text-secondary mt-3">carregando...</p>
    } @else if (a(); as a) {
      <div class="d-flex gap-3 mt-3 flex-wrap flex-sm-nowrap">
        @if (a.poster) {
          <img class="poster" [src]="a.poster" alt="">
        }
        <div>
          <h1 class="h4 mb-1">{{ a.title }}</h1>
          @if (a.anilist; as l) {
            <div class="text-secondary small mb-2">
              @if (l.seasonYear) { {{ l.seasonYear }} · }
              @if (l.episodes) { {{ l.episodes }} eps · }
              @if (l.averageScore) { nota {{ l.averageScore }}/100 · }
              {{ l.genres.join(', ') }}
            </div>
            @if (l.description) {
              <p class="small" [innerHTML]="l.description"></p>
            }
          } @else if (a.anilist_erro) {
            <p class="text-secondary small">AniList indisponível agora; só os dados da Crunchyroll.</p>
          }
          <a class="btn btn-outline-secondary btn-sm" target="_blank" rel="noopener"
             [href]="cr + '/series/' + a.series_id">Abrir na Crunchyroll</a>
          @if (a.anilist; as l) {
            <a class="btn btn-outline-secondary btn-sm ms-2" target="_blank" rel="noopener"
               [href]="l.siteUrl">AniList</a>
          }
        </div>
      </div>

      <h2 class="h6 mt-4">Episódios pendentes</h2>
      @for (t of a.pendentes; track t.title) {
        <details class="border rounded mb-2">
          <summary class="p-2">{{ t.title }}
            <span class="badge text-bg-secondary ms-1">{{ t.episodes.length }}</span>
          </summary>
          <ul class="list-group list-group-flush">
            @for (e of t.episodes; track e.number) {
              <li class="list-group-item small">
                @if (e.id) {
                  <a [href]="cr + '/watch/' + e.id" target="_blank" rel="noopener">
                    {{ e.number }} · {{ e.title }}</a>
                } @else {
                  {{ e.number }} · {{ e.title }}
                }
              </li>
            }
          </ul>
        </details>
      } @empty {
        <p class="text-secondary small">Nada pendente.</p>
      }
    } @else {
      <p class="text-secondary mt-3">anime não encontrado.</p>
    }
  `,
  styles: `
    .poster { width: 160px; aspect-ratio: 2 / 3; object-fit: cover; border-radius: 6px; }
    summary { cursor: pointer; }
  `,
})
export class AnimePage {
  private api = inject(Api);
  cr = CR;

  /** Parâmetro :id da rota (withComponentInputBinding). */
  id = input.required<string>();
  a = signal<AnimeDetalhe | null>(null);
  carregando = signal(true);

  ngOnInit() {
    this.api.anime(this.id()).subscribe({
      next: (a) => {
        this.a.set(a);
        this.carregando.set(false);
      },
      error: () => this.carregando.set(false),
    });
  }
}
