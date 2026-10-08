import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

/** Card de um anime: pôster e título levam ao detalhe; o resto vem de quem usa. */
@Component({
  selector: 'app-anime-card',
  standalone: true,
  imports: [RouterLink],
  template: `
    <div class="card h-100 anime">
      <!-- fora da ordem de tab: o título abaixo é o mesmo link -->
      <a [routerLink]="['/anime', seriesId()]" tabindex="-1" aria-hidden="true">
        @if (poster()) {
          <img class="card-img-top poster" [src]="poster()" alt="" loading="lazy">
        } @else {
          <div class="card-img-top poster sem-poster">{{ title()[0] }}</div>
        }
      </a>
      <div class="card-body p-2">
        <h2 class="h6 card-title mb-2">
          <a class="link-body-emphasis text-decoration-none"
             [routerLink]="['/anime', seriesId()]">{{ title() }}</a>
        </h2>
        <ng-content />
      </div>
      <div class="card-footer p-2 bg-transparent border-0">
        <ng-content select="[acao]" />
      </div>
    </div>
  `,
  styles: `
    .anime {
      transition: transform 0.15s, box-shadow 0.15s;
      &:hover, &:focus-within {
        transform: translateY(-3px);
        box-shadow: 0 6px 18px rgb(0 0 0 / 0.4);
      }
    }
    /* pôster da CR é 2:3; o placeholder ocupa o mesmo espaço para a grade não pular */
    .poster { aspect-ratio: 2 / 3; object-fit: cover; width: 100%; }
    .sem-poster {
      display: grid; place-items: center;
      font-size: 3rem; font-weight: 600;
      color: var(--bs-secondary-color); background: var(--bs-tertiary-bg);
    }
    @media (prefers-reduced-motion: reduce) { .anime { transition: none; } }
  `,
})
export class AnimeCard {
  seriesId = input.required<string>();
  title = input.required<string>();
  poster = input<string | null>(null);
}
