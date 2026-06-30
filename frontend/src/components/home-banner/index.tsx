import { useLang } from '@/i18n'
import decImg from '../../assets/home_banner_dec.png'
import portraitImg from '../../assets/home_banner_portrait.png'
import styles from './index.module.scss'

export default function HomeBanner() {
  const { t } = useLang()
  return (
    <div className={styles.banner}>
      <div className={styles.content}>
        <h1 className={styles.title}>{t.bannerTitle}</h1>
        <p className={styles.subtitle}>{t.bannerSubtitle}</p>
      </div>
      <div className={styles.decoration}>
        <img src={portraitImg} alt="banner" className={styles.portrait} />
        <img src={decImg} alt="decoration" className={styles.decImage} />
      </div>
    </div>
  )
}
