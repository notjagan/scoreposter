from utils import Mod, MODS


class TitleOptions:

    def __init__(self, *, options={}, **kwargs):
        self.sliderbreaks = 0
        self.show_pp = True
        self.show_fc_pp = True
        self.show_combo = True
        self.show_ur = True
        self.message = None

        for key, value in options.items():
            setattr(self, key, value)


def construct_title(score, options):
        if score.mods:
            modstring = ''.join(string for mod, string in MODS.items()
                                if mod in score.mods)
            base = f"{score.artist} - {score.title} [{score.difficulty}] +{modstring} ({score.stars:.2f}*)"
        else:
            base = f"{score.artist} - {score.title} [{score.difficulty}] ({score.stars:.2f}*)"

        fc = score.misses == 0 and options.sliderbreaks == 0

        if score.accuracy == 100:
            base += " SS"
        else:
            base += f" {score.accuracy:.2f}%"
            if score.misses != 0:
                base += f" {score.misses}xMiss"
            if options.sliderbreaks != 0:
                base += f" {options.sliderbreaks}xSB"
            if options.show_combo or not fc:
                base += f" {score.combo}/{score.max_combo}x"
            if fc:
                base += " FC"

        if score.ranking is not None:
            base += f" #{score.ranking}"
        if score.loved:
            base += " LOVED"

        segments = [score.player, base]

        if options.show_pp:
            pp_text = f"{score.pp:.0f}pp"
            if not score.ranked:
                pp_text += " if ranked"
            elif not score.submitted:
                pp_text += " if submitted"
            if options.show_fc_pp and not fc:
                pp_text += f" ({score.fcpp:.0f}pp for FC)"
            segments.append(pp_text)

        if options.show_ur and score.ur is not None:
            dt = Mod.DoubleTime in score.mods or Mod.Nightcore in score.mods
            if dt:
                segments.append(f"{score.ur:.2f} cv.UR")
            else:
                segments.append(f"{score.ur:.2f} UR")

        if options.message is not None:
            segments.append(options.message)

        title = ' | '.join(segments)
        return title
